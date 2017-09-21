# -*- encoding:utf-8 -*-

import tornado.web
import tornado.websocket
import tornado.httpserver
import tornado.ioloop
import tornado.options
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from werkzeug.utils import secure_filename
from os import path
from os.path import basename
import xlwt, smtplib, subprocess
from xlrd import open_workbook
from xlutils.copy import copy
from datetime import datetime
import paramiko,time
from scp import SCPClient
import threading,os
from dbconn import DB

db = DB(host='127.0.0.1',mysql_user='root',mysql_pass='root',mysql_db='sqllog')

def run_command_real_time(cmd):
    ps = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
    while ps.poll() is None:
        line = ps.stdout.readline()
        line = line.strip()
        if line:
            print('Subprogram output: [{%s}]' % (line))
    if ps.returncode == 0:
        print('Subprogram success')
    else:
        print('Subprogram failed')

'''
第一种实时刷新的方式：
cmd = "python subprogram.py"
run_command_real_time(cmd)
#cat subprogram.py
#!/usr/bin/python

import sys
import time

for i in range(5):
    sys.stdout.write('Processing {%s}\n' % (i))
    sys.stdout.flush()
    time.sleep(1)

for i in range(5):
    sys.stderr.write('Error {%s}\n' % (i))
    sys.stderr.flush()
    time.sleep(1)

第二种实时刷新的方式：（可以把sql脚本用shell脚本执行将输出打印到日志文件中，然后用这个方式实时输出。采用多线程处理）
#cmd = "nohup sh subprogram.sh &;tail -F test.log"
cmd = "echo '@ssh_test.sql' | sqlplus / as sysdba >> test.log;tail -F test.log"
run_command_real_time(cmd)
$ cat ssh_test.sql
set line 1000
select * from v$datafile;
insert into test(id,name) values(1,'abc');

# cat subprogram.sh
#!/bin/sh

for i in {1..5}
do
    echo "this is a $i..." >> test.log
    sleep 2
done
'''

# 保存，注销用户连接到websocket的数据，定义发送消息函数
class ws(object):
    '''
    处理websocket 服务器与客户端交互
    '''
    wsRegister = {}

    def register(self, newer):
        '''
            保存新加入的客户端连接、监听实例，并向连接成员发送消息！
        '''
        user = str(newer.get_argument('user'))  # 获取用户
        if user in self.wsRegister:
            self.wsRegister[user].append(newer)
        else:
            self.wsRegister[user] = [newer]

        message = '%s,您处于连接状态，可以进行任务操作了!' % (user)
        self.sendTrigger(user, message)

    def unregister(self, lefter):
        '''
            客户端关闭连接，删除用户对应的客户端连接实例
        '''
        user = str(lefter.get_argument('user'))
        self.wsRegister[user].remove(lefter)

    def sendTrigger(self, user, message):
        '''
            消息触发器，将最新消息返回给对应用户
        '''
        for send in self.wsRegister[user]:
            send.write_message(message)

    def sendall(self,message):
        for key,value in self.wsRegister.items():
            for u in self.wsRegister[key]:
                u.write_message(message)

class websocket(tornado.websocket.WebSocketHandler):
    '''
        websocket， 记录客户端连接，删除客户端连接，接收最新消息
    '''
    def open(self):
        user = str(self.get_argument('user'))
        self.write_message("From:SYS,You connected successful!")
        self.application.ws.register(self)  # 记录客户端连接

    def on_close(self):
        self.application.ws.unregister(self)  # 删除客户端连接

    def on_message(self, user, message):
        self.application.ws.sendTrigger(self, user, message)  # 处理客户端提交的最新消息

class MyThread:
    host_conn = {"JHKDB":['192.168.0.132',22,'root','ychina2017@','JHKDB']}

    def __init__(self):
        self._DBENV = ""
        self._filenames = []
        self._ip = ""
        self._userid = ""
        self._mac = ""

    @property
    def DBENV(self):
        return self._DBENV

    @property
    def filenames(self):
        return self._filenames

    @property
    def ip(self):
        return self._ip

    @property
    def userid(self):
        return self._userid

    @property
    def mac(self):
        return self._mac

    @DBENV.setter
    def DBENV(self,val):
        self._DBENV = val

    @filenames.setter
    def filenames(self, val):
        self._filenames = val

    @ip.setter
    def ip(self, val):
        self._ip = val

    @userid.setter
    def userid(self, val):
        self._userid = val

    @mac.setter
    def mac(self, val):
        self._mac= val

    def allowed_file(self, filename):
        return '.' in filename and filename.rsplit('.', 1)[1] in ['txt', 'sql']

    def run_command(self, cmd):
        if type(cmd) == str:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        else:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE)

        output, err = p.communicate()
        p_status = p.wait()
        result = {"out": output, "err": err, "exit_code": p_status}
        return result

# 主功能类
class sql_piliang(tornado.web.RequestHandler):

    def send_mail(self, attachments):
        mail_from = "jhk65287@163.com"
        mail_subject = "Release Note"
        mail_text = """
		All, this is an email for test to send infomations, please check the attachment to get details.

		Thanks.
		"""
        mail_server = "smtp.163.com"
        username = 'jhk65287@163.com'
        password = 'jhk65287-'

        for mail_address in ['jhk65287@163.com']:
            self.send_one_mail(send_from=mail_from, send_to=mail_address, subject=mail_subject, text=mail_text,
                               files=attachments, user=username, passwd=password, server=mail_server)

    def send_one_mail(self, send_from, send_to, subject, text, files=None, user=None, passwd=None, server="127.0.0.1"):
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = send_from
        msg['To'] = send_to

        msg.attach(MIMEText(text))

        for f in files or []:
            fil = open(f, "rb")
            msg.attach(MIMEApplication(
                fil.read(),
                Content_Disposition='attachment; filename="%s"' % basename(f),
                Name=basename(f)
            ))
            fil.close()

        mail_client = smtplib.SMTP(server)
        mail_client.login(user, passwd)
        mail_client.sendmail(send_from, send_to, msg.as_string())
        mail_client.close()

    def init_sql_perform_history(self,filename):
        timestamp = datetime.now().strftime("%Y%m%d")
        wb = xlwt.Workbook()
        ws = wb.add_sheet(timestamp)
        ws.write(0,0,'filename')
        ws.write(0,1,'username')
        ws.write(0,2,'start_time')
        ws.write(0,3,'end_time')
        ws.write(0,4,'DB_environment')
        ws.save(filename)

    def write_to_xls(self, filename,row,col,value):
        if os.path.isfile(filename):
            rb = open_workbook(filename)
            wb = copy(rb)
            sheet = wb.get_sheet(0)
            sheet.write(row,col,value)
            wb.save(filename)

    def perform(self,host=[],userid="",filenames=[],DBENV=""):
        timestamp = datetime.now().strftime("%Y%m%d")
        basepath = os.path.abspath(os.path.dirname(__file__))
        filename = basepath + "/ORACLE_SQL_PERDORM_%s.xls" % (timestamp)
        if not os.path.isfile(filename):
            self.init_sql_perform_history(filename)
        else:
            pass
        for file in filenames:
            rb = open_workbook(filename)
            new_row = rb.sheets()[0].nrows
            self.write_to_xls(filename,new_row, 0, file)
            self.write_to_xls(filename,new_row, 1, userid)
            starttime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.write_to_xls(filename,new_row, 2, starttime)
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host[0],host[1],host[2],host[3])
            with SCPClient(ssh.get_transport()) as scp:
                scp.put(basepath +'/static/upload/' + file,'/opt/' + file)
            stdin,stdout,stderr = ssh.exec_command("su - oracle -c \"echo '@/opt/" + file + "'|sqlplus cmo/CMOOMC@" + host[4] + "&& echo \"OK\"\"")
            while True:
                line = stdout.readline().strip()
                if line != "OK":
                    self.application.ws.sendTrigger(userid,line)
                else:
                    break
            ssh.close()
            endtime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.write_to_xls(filename,new_row, 3, endtime)
            self.write_to_xls(filename,new_row, 4, DBENV)
        self.application.ws.sendTrigger(userid,"------------------------脚本执行完成--------------------------")

    # GET方法处理入口
    def get(self):
        client = MyThread()
        client.ip = self.request.remote_ip
        userid_cmd = "nmblookup -A %s | tail -5 | grep -vE \"^$|CHINA\" |awk '{if($1==\"MAC\"){$1=$4}}{print $1}'|head -1|cut -b6-|sed 's/\\(.*\\)\\(.\\)$/\\1/'" % (client.ip)
        mac_cmd = "nmblookup -A %s | tail -5 | grep -vE \"^$|CHINA\" |awk '{if($1==\"MAC\"){$1=$4}}{print $1}'|tail -1" % (client.ip)
        # client.userid = client.run_command(userid_cmd)["out"].strip().replace('\n', '').strip()
        # client.mac = client.run_command(mac_cmd)["out"].strip().replace('\n', '').strip()
        client.userid = "jhk"
        client.mac = "a3-23-ef-da-43-e5"
        self.render('sql_piliang.html', ip=client.ip, user_id=client.userid, macaddress=client.mac, DBENV=client.DBENV,filenames=client.filenames)

    # POST方法处理入口
    def post(self):
        client = MyThread()
        client.ip = self.request.remote_ip
        userid_cmd = "nmblookup -A %s | tail -5 | grep -vE \"^$|CHINA\" |awk '{if($1==\"MAC\"){$1=$4}}{print $1}'|head -1|cut -b6-|sed 's/\\(.*\\)\\(.\\)$/\\1/'" % (client.ip)
        mac_cmd = "nmblookup -A %s | tail -5 | grep -vE \"^$|CHINA\" |awk '{if($1==\"MAC\"){$1=$4}}{print $1}'|tail -1" % (client.ip)
        # client.userid = client.run_command(userid_cmd)["out"].strip().replace('\n', '').strip()
        # client.mac = client.run_command(mac_cmd)["out"].strip().replace('\n', '').strip()
        client.userid = "jhk"
        client.mac = "a3-23-ef-da-43-e5"
        if client.userid == "":
            return "请重新访问连接。"
        client.DBENV = self.get_argument("DB_ENV")
        f = self.request.files['files']
        basepath = path.abspath(path.dirname(__file__))
        list = []
        for file in f:
            if file and client.allowed_file(file['filename']):
                filename_time = file['filename'].split('.')[0]+"_"+datetime.now().strftime("%Y%m%d%H%M%S")+".txt"
                file_name = basepath +'/static/upload/%s' % (filename_time)
                # upload_path = path.join(basepath, file_name)
                with open(file_name, 'wb') as up:
                    try:
                        up.write(file['body'].decode('utf-8').encode('gbk'))
                    except:
                        up.write(file['body'])
                list.append(file['filename'])
            else:
                self.render('error.html',filename=file['filename'])
        client.filenames = list
        threads = []
        t1 = threading.Thread(target=self.perform,args=(client.host_conn[client.DBENV],client.userid,client.filenames,client.DBENV,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        self.render('sql_piliang.html', ip=client.ip, user_id=client.userid, macaddress=client.mac,DBENV=client.DBENV, filenames=client.filenames)

class index(tornado.web.RequestHandler):
    def get(self):
        info = get_info(self.request.remote_ip)
        self.render("index.html",ip=info[0],user_id=info[1],macaddress=info[2])

class sql(tornado.web.RequestHandler):
    def get(self):
        info = get_info(self.request.remote_ip)
        self.render("sql.html", ip=info[0], user_id=info[1], macaddress=info[2])

class bkapp(tornado.web.RequestHandler):
    def get(self):
        info = get_info(self.request.remote_ip)
        self.render("bkapp.html", ip=info[0], user_id=info[1], macaddress=info[2])

class cics(tornado.web.RequestHandler):
    def get(self):
        info = get_info(self.request.remote_ip)
        self.render("cics.html", ip=info[0], user_id=info[1], macaddress=info[2])

class sqllog(tornado.web.RequestHandler):
    def get(self):
        info = get_info(self.request.remote_ip)
        self.render("sql_log.html", ip=info[0], user_id=info[1], macaddress=info[2],res="",extr=2)

    def post(self):
        info = get_info(self.request.remote_ip)
        ENV = self.get_argument("ENV")
        gonghao = self.get_argument("gonghao")
        table = self.get_argument("table")
        if self.get_argument("starttime") == "":
            starttime = ""
        else:
            starttime = str(time.mktime(time.strptime(self.get_argument("strattime").replace('T',' ') + ":00","%Y-%m-%d %H:%M:%S"))).split('.')[0]
        if self.get_argument("endtime") == "":
            endtime = ""
        else:
            endtime = str(time.mktime(time.strptime(self.get_argument("endtime").replace('T', ' ') + ":00", "%Y-%m-%d %H:%M:%S"))).split('.')[0]

        opr = self.get_argument("opr")
        if ENV == "":
            s_ENV = ""
        else:
            s_ENV = " and db = \""+ ENV +"\""
        if gonghao == "":
            s_gonghao = ""
        else:
            s_gonghao = " and gonghao = \""+ gonghao +"\""
        if table == "":
            s_table = ""
        else:
            s_table = " and sql_content like '%" + table +"%'"
        if starttime == "":
            s_starttime = ""
        else:
            s_starttime = " and starttime >= "+ starttime +" "
        if endtime == "":
            s_endtime = ""
        else:
            s_endtime = " and endtime <= "+ endtime +" "
        if opr == "":
            s_opr = ""
        else:
            s_opr = " and sql_content like '%" + opr +"%'"
        sql = "select id,db,gonghao,FROM UNIXTIME(starttime) as starttime,FROM UNIXTIME(endtime) as endtime,sql_content from sql_log where 1 = 1 "+s_ENV + s_gonghao + s_starttime + s_endtime + s_table + s_opr +";"
        cur = db.execute(sql)
        res = cur.fetchall()
        if res.__len__() > 1000:
            self.render('sql_log.html', ip=info[0], user_id=info[1], macaddress=info[2], res=res, extr=1)
        else:
            self.render('sql_log.html', ip=info[0], user_id=info[1], macaddress=info[2], res=res, extr=0)

def get_info(ip):
    client = MyThread()
    client.ip = ip
    userid_cmd = "nmblookup -A %s | tail -5 | grep -vE \"^$|CHINA\" |awk '{if($1==\"MAC\"){$1=$4}}{print $1}'|head -1|cut -b6-|sed 's/\\(.*\\)\\(.\\)$/\\1/'" % (client.ip)
    mac_cmd = "nmblookup -A %s | tail -5 | grep -vE \"^$|CHINA\" |awk '{if($1==\"MAC\"){$1=$4}}{print $1}'|tail -1" % (client.ip)
    # client.userid = client.run_command(userid_cmd)["out"].strip().replace('\n', '').strip()
    # client.mac = client.run_command(mac_cmd)["out"].strip().replace('\n', '').strip()
    client.userid = "jhk"
    client.mac = "a3-23-ef-da-43-e5"
    list = [client.ip,client.userid,client.mac]
    return list

def getinfo(branch,par,msg):
    if branch == "trunk":
        host = ['192.168.0.2',22,'root','root','/code/trunk/']
    else:
        host = ['192.168.0.3', 22, 'root', 'root', '/code/branch/']
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host[0], host[1], host[2], host[3])
    cmd = "ls "+ host[4] + par +" | grep -v .svn 2>&1;echo \"OK\""
    stdin, stdout, stderr = ssh.exec_command(cmd)
    data = []
    while True:
        line = stdout.readline().strip()
        if line != "OK":
            data.append(line)
        else:
            break
    ssh.close()
    res = {msg:data}
    return res

class bkapp_op(tornado.web.RequestHandler):
    def post(self):
        msg = self.get_argument("select")
        branch = self.get_argument("branch")
        if msg == "bkapp_name":
            par = "bkapp.release/"
            res = getinfo(branch,par,msg)
            self.write(res)
        elif msg == "svn_path1":
            par = "BUSINESS/"
            res = getinfo(branch, par, msg)
            self.write(res)
        elif msg == "svn_path2":
            par = "BUSINESS/" + self.get_argument("svn_path1") + "/"
            res = getinfo(branch, par, msg)
            self.write(res)
        elif msg == "svn_path3":
            par = "BUSINESS/" + self.get_argument("svn_path1") + "/" + self.get_argument("svn_path2") + "/"
            res = getinfo(branch, par, msg)
            self.write(res)
        else:
            par = "BUSINESS/" + self.get_argument("svn_path1") + "/" + self.get_argument("svn_path2") + "/" + self.get_argument("svn_path3") + "/"
            res = getinfo(branch, par, msg)
            self.write(res)

class bkappstatus(tornado.web.RequestHandler):
    def remote_ssh(self,host,user,cmd):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host[0], host[1], host[2], host[3])
        gonggao = "To-all: "+ user +" 正在查看进程状态..."
        stdin, stdout, stderr = ssh.exec_command(cmd)
        self.application.ws.sendall(gonggao)
        while True:
            line = stdout.readline().strip()
            if line != "OK":
                self.application.ws.sendTrigger(user,line)
            else:
                break
        self.application.ws.sendTrigger(user, "----------------------查看进程状态结束-----------------------")
        ssh.close()

    def post(self):
        ENV = self.get_argument("ENV")
        bkapp_name = self.get_argument("bkapp_name")
        user = self.get_argument("user")
        if ENV == "XQNGCRM" or ENV == "XQNGESOP" or ENV == "XQGDCRM":
            host = ['192.168.0.2',22,'root','root']
        else:
            host = ['192.168.0.3', 22, 'root', 'root']
        precmd = "su - hwcrm -c \"cd /" + ENV + "/bkapp/bgapps/"
        cmd = precmd + bkapp_name +" 2>&1;bkapp show ZJ \" 2>&1;echo \"OK\""
        threads = []
        t1 = threading.Thread(target=self.remote_ssh,args=(host,user,cmd,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg":""}
        self.write(res)

class bkappopr(tornado.web.RequestHandler):
    def remote_ssh(self, host, user, ENV, cmd,bkapp_name,opr):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host[0], host[1], host[2], host[3])
        starttime = str(time.time()).split('.')[0]
        gonggao = "To-all: " + user + " 正在"+ opr +" "+ ENV +"进程: "+ bkapp_name
        stdin, stdout, stderr = ssh.exec_command(cmd)
        self.application.ws.sendall(gonggao)
        while True:
            line = stdout.readline().strip()
            if line != "OK":
                self.application.ws.sendTrigger(user, line)
            else:
                break
        self.application.ws.sendTrigger(user, "----------------------BKAPP操作完成-----------------------")
        ssh.close()
        endtime = str(time.time()).split('.')[0]
        sqltext = "Operatoe BKAPP "+ bkapp_name +" to "+ opr
        sql = "insert into sql_log VALUES('',\""+ ENV +" BKAPP\",\""+ user +"\","+ starttime +","+ endtime +",\""+ sqltext +"\");"
        db.execute(sql)

    def post(self):
        ENV = self.get_argument("ENV")
        bkapp_name = self.get_argument("bkapp_name")
        user = self.get_argument("user")
        opr = self.get_argument("opr")
        if ENV == "XQNGCRM" or ENV == "XQNGESOP" or ENV == "XQGDCRM":
            host = ['192.168.0.2', 22, 'root', 'root']
        else:
            host = ['192.168.0.3', 22, 'root', 'root']
        precmd = "su - hwcrm -c \"cd /" + ENV + "/bkapp/bgapps/"
        if opr == "stop":
            cmd = precmd + bkapp_name +" 2>&1;bkapp stop ZJ\" 2>&1;echo \"OK\""
        else:
            cmd = precmd + bkapp_name + " 2>&1;bkapp start ZJ \" 2>&1;echo \"OK\""
        threads = []
        t1 = threading.Thread(target=self.remote_ssh, args=(host, user,ENV, cmd,bkapp_name,opr,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg": ""}
        self.write(res)

class bkappcompiler(tornado.web.RequestHandler):
    def remote_ssh(self, host, user, branch, cmd, bkapp_name):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host[0], host[1], host[2], host[3])
        starttime = str(time.time()).split('.')[0]
        gonggao = "To-all: " + user + " 正在编译" + branch + "进程: " + bkapp_name
        stdin, stdout, stderr = ssh.exec_command(cmd)
        self.application.ws.sendall(gonggao)
        while True:
            line = stdout.readline().strip()
            if line != "OK":
                self.application.ws.sendTrigger(user, line)
            else:
                break
        self.application.ws.sendTrigger(user, "----------------------BKAPP编译完成-----------------------")
        ssh.close()
        endtime = str(time.time()).split('.')[0]
        sqltext = "Compiler BKAPP " + bkapp_name
        sql = "insert into sql_log VALUES('',\"" + branch + " BKAPP\",\"" + user + "\"," + starttime + "," + endtime + ",\"" + sqltext + "\");"
        db.execute(sql)

    def post(self):
        branch = self.get_argument("branch")
        bkapp_name = self.get_argument("bkapp_name")
        user = self.get_argument("user")
        if branch == "trunk":
            host = ['192.168.0.2', 22, 'root', 'root','/code/trunk/']
            cmd = "su - cmo -c \"grep \\\"/"+ bkapp_name +"\\\" /code/trunk/bkapp.list.ini > /code/trunk/bkapp.list_one.ini 2>&1; "+ \
                  host[4] +"bkapp.make_one.sh 2>&1 \"; echo \"OK\""
        else:
            host = ['192.168.0.3', 22, 'root', 'root','/code/branch/']
            cmd = "su - cmo -c \"grep \\\"/" + bkapp_name + "\\\" /code/branch/bkapp.list.ini > /code/branch/bkapp.list_one.ini 2>&1; " + \
                  host[4] + "bkapp.make_one.sh 2>&1 \"; echo \"OK\""
        threads = []
        t1 = threading.Thread(target=self.remote_ssh, args=(host, user, branch, cmd, bkapp_name,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg": ""}
        self.write(res)

class bkappdeploy(tornado.web.RequestHandler):
    def remote_ssh(self, envinfo, user, ENV, cmd, bkapp_name):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(envinfo[0], envinfo[1], envinfo[2], envinfo[3])
        starttime = str(time.time()).split('.')[0]
        gonggao = "To-all: " + user + " 正在发布" + ENV + "进程: " + bkapp_name
        stdin, stdout, stderr = ssh.exec_command(cmd)
        self.application.ws.sendall(gonggao)
        while True:
            line = stdout.readline().strip()
            if line != "OK":
                self.application.ws.sendTrigger(user, line)
            else:
                break
        self.application.ws.sendTrigger(user, "----------------------BKAPP发布完成-----------------------")
        ssh.close()
        endtime = str(time.time()).split('.')[0]
        sqltext = "Deploy BKAPP " + bkapp_name
        sql = "insert into sql_log VALUES('',\"" + ENV + " BKAPP\",\"" + user + "\"," + starttime + "," + endtime + ",\"" + sqltext + "\");"
        db.execute(sql)

    def post(self):
        ENV = self.get_argument("ENV")
        bkapp_name = self.get_argument("bkapp_name")
        user = self.get_argument("user")
        if ENV == "XQNGCRM" or ENV == "XQNGESOP" or ENV == "XQGDCRM":
            envinfo = ['192.168.0.2', 22, 'root', 'root']
        else:
            envinfo = ['192.168.0.3', 22, 'root', 'root']
        cmd = "su - hwcrm -c \"/" + ENV + "/bkapp/deploybkapp.sh "+ bkapp_name +" 2>&1\";echo \"OK\""
        threads = []
        t1 = threading.Thread(target=self.remote_ssh, args=(envinfo, user, ENV, cmd, bkapp_name,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg": ""}
        self.write(res)

class cics_op(tornado.web.RequestHandler):
    def post(self):
        msg = self.get_argument("select")
        branch = self.get_argument("branch")
        if msg == "cics_name":
            par = "cics.release/"
            res = getinfo(branch,par,msg)
            self.write(res)
        elif msg == "svn_path1":
            par = "BUSINESS/"
            res = getinfo(branch, par, msg)
            self.write(res)
        elif msg == "svn_path2":
            par = "BUSINESS/" + self.get_argument("svn_path1") + "/"
            res = getinfo(branch, par, msg)
            self.write(res)
        elif msg == "svn_path3":
            par = "BUSINESS/" + self.get_argument("svn_path1") + "/" + self.get_argument("svn_path2") + "/"
            res = getinfo(branch, par, msg)
            self.write(res)
        else:
            par = "BUSINESS/" + self.get_argument("svn_path1") + "/" + self.get_argument("svn_path2") + "/" + self.get_argument("svn_path3") + "/"
            res = getinfo(branch, par, msg)
            self.write(res)

class update(tornado.web.RequestHandler):
    def remote_ssh(self, host, user, cmd, branch,path):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host[0], host[1], host[2], host[3])
        starttime = str(time.time()).split('.')[0]
        stdin, stdout, stderr = ssh.exec_command(cmd)
        while True:
            line = stdout.readline().strip()
            if line != "OK":
                self.application.ws.sendTrigger(user, line)
            else:
                break
        self.application.ws.sendTrigger(user, "----------------------更新完成------------------------")
        ssh.close()
        endtime = str(time.time()).split('.')[0]
        sqltext = "Update local svn code on:"+ host[4] + path
        sql = "insert into sql_log VALUES('',\"" + branch + " BKAPP\",\"" + user + "\"," + starttime + "," + endtime + ",\"" + sqltext + "\");"
        db.execute(sql)

    def post(self):
        branch = self.get_argument("branch")
        path = self.get_argument("path")
        user = self.get_argument("user")
        if branch == "trunk":
            host = ['192.168.0.2', 22, 'root', 'root','/code/trunk/BUSINESS/']
        else:
            host = ['192.168.0.3', 22, 'root', 'root','/code/branch/BUSINESS/']
        cmd = "svn up "+ host[4] + path + " 2>&1;echo \"OK\""
        threads = []
        t1 = threading.Thread(target=self.remote_ssh, args=(host, user, cmd, branch,path,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg": ""}
        self.write(res)

class cicsstatus(tornado.web.RequestHandler):
    def remote_ssh(self, host, user, cmd):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host[0], host[1], host[2], host[3])
        stdin, stdout, stderr = ssh.exec_command(cmd)
        while True:
            line = stdout.readline().strip()
            if line != "OK":
                self.application.ws.sendTrigger(user, line)
            else:
                break
        self.application.ws.sendTrigger(user, "----------------------查看CICS状态结束-----------------------")
        ssh.close()

    def post(self):
        ENV = self.get_argument("ENV")
        cics_name = self.get_argument("cics_name").split('.')[0] + ".so"
        user = self.get_argument("user")
        if ENV == "XQNGCRM" or ENV == "XQNGESOP" or ENV == "XQGDCRM":
            host = ['192.168.0.2', 22, 'root', 'root','/code/trunk/BUSINESS/']
        else:
            host = ['192.168.0.3', 22, 'root', 'root','/code/branch/BUSINESS/']
        cmd = "su - cmo -c \"cd /" + ENV + "/cicsapp/;getinfo "+ cics_name +";lssrc -a | grep cics 2>&1;echo \"OK\""
        threads = []
        t1 = threading.Thread(target=self.remote_ssh, args=(host, user, cmd,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg": ""}
        self.write(res)

class cicsopr(tornado.web.RequestHandler):
    def remote_ssh(self, host, user, ENV, cmd, opr):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host[0], host[1], host[2], host[3])
        starttime = str(time.time()).split('.')[0]
        gonggao = "To-all: " + user + " 正在" + opr + " " + ENV + "的CICS."
        stdin, stdout, stderr = ssh.exec_command(cmd)
        self.application.ws.sendall(gonggao)
        while True:
            line = stdout.readline().strip()
            if line != "OK":
                self.application.ws.sendTrigger(user, line)
            else:
                break
        self.application.ws.sendTrigger(user, "----------------------CICS操作完成------------------------")
        ssh.close()
        endtime = str(time.time()).split('.')[0]
        sqltext = "Operatoe CICS " + ENV + " to " + opr
        sql = "insert into sql_log VALUES('',\"" + ENV + " CICS\",\"" + user + "\"," + starttime + "," + endtime + ",\"" + sqltext + "\");"
        db.execute(sql)

    def post(self):
        ENV = self.get_argument("ENV")
        user = self.get_argument("user")
        opr = self.get_argument("opr")
        if ENV == "XQNGCRM" or ENV == "XQNGESOP" or ENV == "XQGDCRM":
            host = ['192.168.0.2', 22, 'root', 'root']
        else:
            host = ['192.168.0.3', 22, 'root', 'root']
        if opr == "stop":
            cmd = "cicscp -v stop region "+ ENV +" -f 2>&1;cicscp -v stop region "+ ENV +" -f 2>&1;echo \"OK\""
        else:
            cmd = "cicscp -v start region "+ ENV +" 2>&1;echo \"OK\""
        threads = []
        t1 = threading.Thread(target=self.remote_ssh, args=(host, user, ENV, cmd, opr,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg": ""}
        self.write(res)

class cicscompiler(tornado.web.RequestHandler):
    def remote_ssh(self, host, user, branch, cmd, cics_name):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host[0], host[1], host[2], host[3])
        starttime = str(time.time()).split('.')[0]
        gonggao = "To-all: " + user + " 正在编译" + branch + "  条带: " + cics_name
        stdin, stdout, stderr = ssh.exec_command(cmd)
        self.application.ws.sendall(gonggao)
        while True:
            line = stdout.readline().strip()
            if line != "OK":
                self.application.ws.sendTrigger(user, line)
            else:
                break
        self.application.ws.sendTrigger(user, "----------------------CICS编译完成------------------------")
        ssh.close()
        endtime = str(time.time()).split('.')[0]
        sqltext = "Compiler CICS " + cics_name
        sql = "insert into sql_log VALUES('',\"" + branch + " \",\"" + user + "\"," + starttime + "," + endtime + ",\"" + sqltext + "\");"
        db.execute(sql)

    def post(self):
        branch = self.get_argument("branch")
        cics_name = self.get_argument("cics_name")
        user = self.get_argument("user")
        cics_name = cics_name.split('.')[0]+ ".so"
        if branch == "trunk":
            host = ['192.168.0.2', 22, 'root', 'root', '/code/trunk/']
        else:
            host = ['192.168.0.3', 22, 'root', 'root', '/code/branch/']
        cmd = "su - cmo -c \"" + host[4] + "cics.make.sh " + cics_name + " 2>&1 \"; echo \"OK\""
        threads = []
        t1 = threading.Thread(target=self.remote_ssh, args=(host, user, branch, cmd, cics_name,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg": ""}
        self.write(res)

class cicsdeploy(tornado.web.RequestHandler):
    def remote_ssh(self, envinfo, user, ENV, cmd, cics_name):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(envinfo[0], envinfo[1], envinfo[2], envinfo[3])
        starttime = str(time.time()).split('.')[0]
        gonggao = "To-all: " + user + " 正在发布" + ENV + " 条带: " + cics_name
        stdin, stdout, stderr = ssh.exec_command(cmd)
        self.application.ws.sendall(gonggao)
        while True:
            line = stdout.readline().strip()
            if line != "OK":
                self.application.ws.sendTrigger(user, line)
            else:
                break
        self.application.ws.sendTrigger(user, "----------------------CICS发布完成------------------------")
        ssh.close()
        endtime = str(time.time()).split('.')[0]
        sqltext = "Deploy CICS " + ENV
        sql = "insert into sql_log VALUES('',\"" + ENV + " CICS\",\"" + user + "\"," + starttime + "," + endtime + ",\"" + sqltext + "\");"
        db.execute(sql)

    def post(self):
        ENV = self.get_argument("ENV")
        cics_name = self.get_argument("cics_name")
        user = self.get_argument("user")
        cics_name = cics_name.split('.')[0] + ".so"
        if ENV == "XQNGCRM" or ENV == "XQNGESOP" or ENV == "XQGDCRM":
            envinfo = ['192.168.0.2', 22, 'root', 'root']
        else:
            envinfo = ['192.168.0.3', 22, 'root', 'root']
        cmd = "su - cmo -c \"/" + ENV + "/cicsapp/deploysomecics.sh " + cics_name + " 2>&1\";echo \"OK\""
        threads = []
        t1 = threading.Thread(target=self.remote_ssh, args=(envinfo, user, ENV, cmd, cics_name,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg": ""}
        self.write(res)

class sql_run(tornado.web.RequestHandler):
    def remote_ssh(self, host, user, ENV, sqltext):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host[0], host[1], host[2], host[3])
        starttime = str(time.time()).split('.')[0]
        stdin, stdout, stderr = ssh.exec_command("su - oracle -c \"echo \\\""+ sqltext +"\\\"|sqlplus WEBCMO/WEBCMOO@"+ host[4] +"\" 2>&1;echo \"OK\"")
        i = 0   #限制查询的记录数标志
        while True:
            if i <= 500:
                line = stdout.readline().strip()
                if line != "OK":
                    self.application.ws.sendTrigger(user, line)
                else:
                    break
            else:
                self.application.ws.sendTrigger(user, "------------------查询结果集超过500条记录---------------------")
                break
        self.application.ws.sendTrigger(user, "----------------------执行结束------------------------")
        ssh.close()
        endtime = str(time.time()).split('.')[0]
        sql = "insert into sql_log VALUES('',\"" + ENV + "\",\"" + user + "\"," + starttime + "," + endtime + ",\"" + sqltext.decode('gbk') + "\");"
        db.execute(sql)

    def post(self):
        client = MyThread()
        sqltext = self.get_argument("sqltext").decode('utf-8').encode('gbk')
        ENV = self.get_argument("ENV")
        user = self.get_argument("user")
        host = client.host_conn[ENV]
        threads = []
        t1 = threading.Thread(target=self.remote_ssh, args=(host, user, ENV, sqltext,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg": ""}
        self.write(res)

class gongdan(tornado.web.RequestHandler):
    def remote_ssh(self, host, user, ENV, cmd, task):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host[0], host[1], host[2], host[3])
        starttime = str(time.time()).split('.')[0]
        if task == "update" or task == "compiler" or task == "status":
            pass
        else:
            gonggao = "To-all: "+ user +" 正在 "+ task +" "+ ENV +"的工单进程."
            self.application.ws.sendall(gonggao)
        stdin, stdout, stderr = ssh.exec_command(cmd)
        while True:
            line = stdout.readline().strip()
            if line != "OK":
                self.application.ws.sendTrigger(user, line)
            else:
                break
        self.application.ws.sendTrigger(user, "----------------------执行结束------------------------")
        ssh.close()
        endtime = str(time.time()).split('.')[0]
        sql = "insert into sql_log VALUES('',\"" + ENV + "\",\"" + user + "\"," + starttime + "," + endtime + ",\"" + cmd + "\");"
        db.execute(sql)

    def get(self):
        info = get_info(self.request.remote_ip)
        self.render('gongdan.html',ip=info[0],user_id=info[1],macaddress=info[2])

    def post(self):
        task = self.get_argument("task")
        host = []
        cmd = ""
        if task == "update":
            branch = self.get_argument("branch")
            user = self.get_argument("user")
            host = ['192.168.0.2',22,'root','root']
            if branch == "trunk":
                ENV = "trunk"
                path = "/code/trunk/NGSENDWF/"
            else:
                ENV = "branch"
                path = "/code/branch/NGSENDWF/"
            cmd = "su - cmo -c 'cd "+ path +";svn up .' 2>&1;echo 'OK'"
        elif task == "status":
            ENV = self.get_argument("ENV")
            user = self.get_argument("user")
            if ENV == "XQNGCRM" or ENV == "XQNGESOP":
                host = ['192.168.0.2', 22, 'root', 'root']
            else:
                host = ['192.168.0.3', 22, 'root', 'root']
            cmd = "ps -ef | grep NGSENDWF | grep "+ ENV +" 2>&1;echo 'OK'"
        elif task == "start":
            ENV = self.get_argument("ENV")
            user = self.get_argument("user")
            if ENV == "XQNGCRM" or ENV == "XQNGESOP":
                host = ['192.168.0.2', 22, 'root', 'root']
            else:
                host = ['192.168.0.3', 22, 'root', 'root']
            cmd = "cd /"+ ENV +"/bkapp/NGSENDWF/;.runNGSENDWF.sh 2>&1;echo 'OK'"
        elif task == "stop":
            ENV = self.get_argument("ENV")
            user = self.get_argument("user")
            if ENV == "XQNGCRM" or ENV == "XQNGESOP":
                host = ['192.168.0.2', 22, 'root', 'root']
            else:
                host = ['192.168.0.3', 22, 'root', 'root']
                cmd = "cd /" + ENV + "/bkapp/NGSENDWF/;.stopNGSENDWF.sh 2>&1;echo 'OK'"
        elif task == "compiler":
            branch = self.get_argument("branch")
            user = self.get_argument("user")
            host = ['192.168.0.2', 22, 'root', 'root']
            if branch == "trunk":
                ENV = "trunk"
                path = "/code/trunk/NGSENDWF/"
                cmd = "su - cmo -c 'cd "+ path +";do.sh;cp build/*.jar ../../lastversion/' 2>&1;echo 'OK'"
            else:
                ENV = "branch"
                path = "/code/branch/NGSENDWF/"
                cmd = "su - cmo -c 'cd " + path + ";do.sh;cp build/*.jar ../../lastversion/' 2>&1;echo 'OK'"
        elif task == "deploy":
            ENV = self.get_argument("ENV")
            user = self.get_argument("user")
            if ENV == "XQNGCRM" or ENV == "XQNGESOP":
                host = ['192.168.0.2', 22, 'root', 'root']
            else:
                host = ['192.168.0.3', 22, 'root', 'root']
            cmd = "cd /"+ ENV +"/bkapp/NGSENDWF/;ftp.sh;./stopNGSENDWF.sh;./runNGSENDWF.sh 2>&1;echo 'OK'"
        else:       #真实/模拟桩切换
            ENV = self.get_argument("ENV")
            user = self.get_argument("user")
            if ENV == "XQNGCRM" or ENV == "XQNGESOP":
                host = ['192.168.0.2', 22, 'root', 'root']
            else:
                host = ['192.168.0.3', 22, 'root', 'root']

        threads = []
        t1 = threading.Thread(target=self.remote_ssh, args=(host, user, ENV, cmd,task,))
        threads.append(t1)
        for t in threads:
            t.setDaemon(True)
            t.start()
        res = {"msg": ""}
        self.write(res)

class sql_awr(tornado.web.RequestHandler):
    def remote_ssh(self, host, ENV,one,two,three,now_c):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host[0], host[1], host[2], host[3])
        basepath = os.path.abspath(os.path.dirname(__file__))
        with SCPClient(ssh.get_transport()) as scp:
            scp.put('/awr.sh','/home/oracle/')
        stdin, stdout, stderr = ssh.exec_command(
            "su - oracle -c \"/home/oracle/awr.sh "+ one +" "+ two +" "+ three +" "+ ENV +" "+ now_c + " 2>&1\";rm -f /home/oracle/awr.sh;echo \"OK\"")
        while True:
            if stdout.readline().strip() == "OK":
                with SCPClient(ssh.get_transport()) as scp:
                    scp.get("/home/oracle/AWR_shahang_%s_%s.html" % (ENV,now_c), basepath +'/static/uploads/')
            else:
                break
        ssh.close()

    def run_command(self,cmd):
        if type(cmd) == unicode:
            p = subprocess.Popen(cmd,stdout=subprocess.PIPE,shell=True)
        else:
            p = subprocess.Popen(cmd,stdout=subprocess.PIPE)
        output,err = p.communicate()
        p_status = p.wait()
        result = {"out":output,"err":err,"exit_code":p_status}
        return result

    def get(self):
        info = get_info(self.request.remote_ip)
        self.render('sql_awr.html',ip=info[0], user_id=info[1], macaddress=info[2])

    def post(self):
        ENV = self.get_argument("ENV")
        starttime = self.get_argument("starttime")
        endtime = self.get_argument("endtime")
        table = self.get_argument("table")
        if ENV == "getsqlscript":
            basepath = os.path.abspath(os.path.dirname(__file__))
            if starttime == "" and endtime != "":
                endtime = endtime.replace('T','').replace('-','').replace(':','') + "00"
                par = "| awk -F '_|[.]' '{if($(NF-1)<="+ endtime +"){print $0}}' "
            elif starttime != "" and endtime == "":
                starttime = starttime.replace('T','').replace('-','').replace(':','') + "00"
                par = "| awk -F '_|[.]' '{if($(NF-1)>="+ starttime +"){print $0}}' "
            elif starttime != "" and endtime != "":
                starttime = starttime.replace('T','').replace('-','').replace(':','') + "00"
                endtime = endtime.replace('T', '').replace('-', '').replace(':', '') + "00"
                par = "| awk -F '_|[.]' '{if($(NF-1)>="+ starttime +" && $(NF-1)<="+ endtime +"){print $0}}' "
            else:
                par = ""
            cmd = "ls "+ basepath +"/static/uploads/ "+ par +"|grep '"+ table +"'"
            cmd_res = self.run_command(cmd)["out"].split('\n')
            res = {"files":cmd_res}
            self.write(res)
        else:
            client = MyThread()
            host = client.host_conn[ENV]
            starttime_d = int(starttime.split('T')[0].split('-')[2])
            endtime_d = int(endtime.split('T')[0].split('-')[2])
            starttime_h = int(starttime.split('T')[0].split('-')[0])
            endtime_h = int(endtime.split('T')[0].split('-')[0])
            now_d = int(str(datetime.now()).split(' ')[0].split('-')[2])
            now_h = int(str(datetime.now()).split(' ')[1].split(':')[0])
            now_c = datetime.now().strftime("%Y%m%d%H%M%S")
            one = now_d - starttime_d
            if one > 5:
                res = {"files":"dayout"}
                self.write(res)
            else:
                two = (24 - starttime_h) + (now_d - starttime_d -1) * 24 + now_h
                three = (24 - endtime_h) + (now_d - endtime_d - 1) * 24 + now_h
                threads = []
                t1 = threading.Thread(target=self.remote_ssh, args=(host[4], str(one), str(two), str(three),now_c,))
                threads.append(t1)
                for t in threads:
                    t.setDaemon(True)
                    t.start()
                res = {"msg": ""}
                self.write(res)

# tornado框架应用配置访问入口
class Application(tornado.web.Application):
    def __init__(self):
        self.ws = ws()

        handlers = [
            (r'/', index),
            (r'/sql_piliang', sql_piliang),
            (r'/sql', sql),
            (r'/sql_run', sql_run),
            (r'/sqllog', sqllog),
            (r'/update', update),
            (r'/bkapp', bkapp),
            (r'/bkapp_op', bkapp_op),
            (r'/bkappopr', bkappopr),
            (r'/bkappstatus', bkappstatus),
            (r'/bkappcompiler', bkappcompiler),
            (r'/bkappdeploy', bkappdeploy),
            (r'/cics', cics),
            (r'/cics_op', cics_op),
            (r'/cicsopr', cicsopr),
            (r'/cicsstatus', cicsstatus),
            (r'/cicscompiler', cicscompiler),
            (r'/cicsdeploy', cicsdeploy),
            (r'/gongdan', gongdan),
            (r'/sql_awr', sql_awr),
            (r'/websocket/', websocket),

        ]

        settings = {
            'template_path': 'templates',
            'static_path': 'static'
        }

        tornado.web.Application.__init__(self, handlers, **settings)

# 主函数
if __name__ == '__main__':
    tornado.options.parse_command_line()
    server = tornado.httpserver.HTTPServer(Application())
    server.listen(8080)
    tornado.ioloop.IOLoop.instance().start()