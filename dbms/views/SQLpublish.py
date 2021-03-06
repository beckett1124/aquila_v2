from django.shortcuts import render, HttpResponse
from django.views import View
from model_model import models
from dbms import forms
from back.views.AuthAccount import AuthAccount, GetUserInfo
from django.utils.decorators import method_decorator
from scripts import functions
from scripts.functions import JsonCustomEncoder, get_uuid, result_tran
from scripts.Inception import Inception
import json, datetime


@method_decorator(AuthAccount, name='dispatch')
class SqlCommit(View):

    def __init__(self, **kwargs):
        super(SqlCommit, self).__init__(**kwargs)
        self.result_dict = {'data': {}, 'status': 0, 'error': '', 'running': 0, 'post_flag': 0}

    def get(self, request):
        user_info = GetUserInfo(request)
        obj = forms.SqlComForm()

        return render(request,
                      'inception/SqlCommit.html',
                      {'user_info': user_info,
                       'SqlComFormObj': obj,
                       'AuditResult': self.result_dict,
                       })

    def post(self, request):
        user_info = GetUserInfo(request)
        obj = forms.SqlComForm(request.POST)

        if obj.is_valid():
            self.result_dict['post_flag'] = 1
            work_order_id = get_uuid()
            host_id = obj.cleaned_data['host']
            port = obj.cleaned_data['port']
            db_name = obj.cleaned_data['db_name']
            run_time = obj.cleaned_data['run_time']
            sql_content = 'use ' + db_name + ';' + obj.cleaned_data['sql_content']

            db_info = models.HostAPPAccount.objects.filter(host_id=host_id,
                                                           host__app_type__app_name='MySQL',
                                                           app_port=port
                                                           ).values('host__host_ip', 'app_user', 'app_pass')
            # check db info
            if not db_info:
                self.result_dict['error'] = '无当前数据库信息，请确认数据库地址与端口号！！！'
            # check db login
            else:
                db_host = db_info[0]['host__host_ip']
                db_user = db_info[0]['app_user']
                db_passwd = db_info[0]['app_pass']

                db_check_flag = functions.DBAPI(db_host, db_user, db_passwd, port)
                if db_check_flag.error:
                    self.result_dict['error'] = '无连接当前数据库，请确认联系管理员！！！'
                else:
                    self.result_dict['status'] = 1
                if self.result_dict['status'] == 1:
                    # auto audit sql
                    ince = Inception(db_host=db_host,
                                     db_user=db_user,
                                     db_passwd=db_passwd,
                                     db_port=port,
                                     sql_content=sql_content)
                    result = ince.audit_sql()
                    if isinstance(result, dict):
                        self.result_dict['status'] = 0
                        self.result_dict['error'] = '无连接 Inception，请联系管理员！！！'
                    else:
                        self.result_dict = result_tran(result, self.result_dict)

                if obj.cleaned_data['is_commit'] == '1' and self.result_dict['status'] == 1:
                        # commit audit sql
                        self.result_dict['running'] = 1
                        master_ip = functions.get_master(db_host, db_user, db_passwd, port, db_name)

                        # InceptionWorkOrderInfo
                        models.InceptionWorkOrderInfo.objects.create(
                            work_title=obj.cleaned_data['title'],
                            work_order_id=work_order_id,
                            work_user=user_info[0]['user_name'],
                            db_host=db_info[0]['host__host_ip'],
                            db_name=db_name,
                            master_host=master_ip,
                            review_user_id=obj.cleaned_data['review_name'],
                            work_cron_time=datetime.datetime.now() if run_time == None else run_time,
                            comm=obj.cleaned_data['comm']
                        )

                        # InceptionAuditDetail
                        for id in self.result_dict['data']:
                            models.InceptionAuditDetail.objects.create(
                                work_order_id=work_order_id,
                                sql_sid=id,
                                flag=1,
                                status=self.result_dict['data'][id]['status'],
                                error_msg=self.result_dict['data'][id]['error_msg'],
                                sql_content=self.result_dict['data'][id]['sql'],
                                aff_row=self.result_dict['data'][id]['rows'],
                                rollback_id=self.result_dict['data'][id]['rollback_id'],
                                backup_dbname=self.result_dict['data'][id]['backup_dbname'],
                                execute_time=self.result_dict['data'][id]['execute_time'],
                                sql_hash=self.result_dict['data'][id]['sql_hash']
                            )

                        # InceAuditSQLContent
                        models.InceAuditSQLContent.objects.create(
                            work_order_id=work_order_id,
                            sql_content=obj.cleaned_data['sql_content']
                        )
                        # WorkOrderTask
                        models.WorkOrderTask.objects.create(
                            work_order_id=work_order_id,
                            host_ip=master_ip,
                            app_user=db_user,
                            app_pass=db_passwd,
                            app_port=port,
                            db_name=db_name,
                            work_status=0
                        )
        else:
            self.result_dict['error'] = json.dumps(obj.errors)
        return render(request,
                      'inception/SqlCommit.html',
                      {'user_info': user_info,
                       'SqlComFormObj': obj,
                       'AuditResult': self.result_dict,
                       })


@method_decorator(AuthAccount, name='dispatch')
class SqlAudit(View):
    def get(self, request):
        user_info = GetUserInfo(request)
        audit_sql_info = models.InceptionWorkOrderInfo.objects.filter(
            review_user=user_info[0]['id'],
            review_status=10
        ).all()
        detail_sql_info = models.InceptionWorkOrderInfo.objects.filter(
            review_user=user_info[0]['id'],
            review_status=10
        ).all().values(
            'work_order_id',
            'inceptionauditdetail__sql_sid',
            'inceptionauditdetail__status',
            'inceptionauditdetail__error_msg',
            'inceptionauditdetail__sql_content',
            'inceptionauditdetail__aff_row',
        )

        return render(request, 'inception/SqlAudit.html', {'user_info': user_info,
                                                           'audit_sql_info': audit_sql_info,
                                                           'detail_sql_info': detail_sql_info})

    def post(self, request):
        result_dict = {'status': 0, 'data': 1}
        user_info = GetUserInfo(request)
        audit_flag = request.POST.get('flag', None)
        wid = request.POST.get('wid', None)
        now_time = datetime.datetime.now()
        if audit_flag and wid:
            if audit_flag == '驳回':
                audit_flag = 1
            else:
                audit_flag = 0
            try:
                models.InceptionWorkOrderInfo.objects.filter(work_order_id=wid).update(review_status=audit_flag,
                                                                                       review_time=now_time)
                result_dict['status'] = 1
            except Exception as e:
                result_dict['data'] = str(e)
        else:
            result_dict['data'] = '发送数据不对, 请联系管理员'
        return HttpResponse(json.dumps(result_dict))


@method_decorator(AuthAccount, name='dispatch')
class SqlRunning(View):
    def get(self, request):
        user_info = GetUserInfo(request)
        run_work_info = models.InceptionWorkOrderInfo.objects.filter(work_user=user_info[0]['user_name'],
                                                                     review_status=0).all()
        detail_sql_info = models.InceptionWorkOrderInfo.objects.filter(
            review_user=user_info[0]['id'],
            review_status=0
        ).all().values(
            'work_order_id',
            'inceptionauditdetail__sql_sid',
            'inceptionauditdetail__status',
            'inceptionauditdetail__error_msg',
            'inceptionauditdetail__sql_content',
            'inceptionauditdetail__aff_row',
        )
        return render(request, 'inception/SqlRunning.html', {'user_info': user_info,
                                                             'run_work_info': run_work_info,
                                                             'detail_sql_info': detail_sql_info})

    def post(self, request):
        result_dict = {'status': 0, 'data': 1 }
        run_flag = request.POST.get('flag', None)
        wid = request.POST.get('wid', None)


        task_info = models.WorkOrderTask.objects.filter(work_order_id=wid).values(
            'work_order__inceauditsqlcontent__sql_content',
            'host_ip',
            'app_pass',
            'app_user',
            'app_port'
        )
        ince = Inception(db_host=task_info[0]['host_ip'],
                         db_user=task_info[0]['app_user'],
                         db_passwd=task_info[0]['app_pass'],
                         db_port=task_info[0]['app_port'],
                         sql_content=task_info[0]['work_order__inceauditsqlcontent__sql_content'],
                         )
        # 提交到后台执行,

        return HttpResponse(json.dumps(result_dict))


@method_decorator(AuthAccount, name='dispatch')
class SqlView(View):
    def get(self, request):
        user_info = GetUserInfo(request)
        review_work_info = models.InceptionWorkOrderInfo.objects.filter(
            work_user=user_info[0]['user_name']).all()

        audit_work_info = models.InceptionWorkOrderInfo.objects.filter(review_user=user_info[0]['id'],
                                                                       review_status=10).all()

        detail_sql_info = models.InceptionWorkOrderInfo.objects.filter(
            review_user=user_info[0]['id']
        ).all().values(
            'work_order_id',
            'inceptionauditdetail__sql_sid',
            'inceptionauditdetail__status',
            'inceptionauditdetail__error_msg',
            'inceptionauditdetail__sql_content',
            'inceptionauditdetail__aff_row',
        )

        return render(request, 'inception/SqlWorkView.html', {'user_info': user_info,
                                                              'review_work_info': review_work_info,
                                                              'audit_work_info': audit_work_info,
                                                              'detail_sql_info': detail_sql_info})

    def post(self, request):
        user_info = GetUserInfo(request)
        return render(request, 'HostGroupManage.html', {'user_info': user_info})


@method_decorator(AuthAccount, name='dispatch')
class SqlDetail(View):
    def get(self, request, wid):
        user_info = GetUserInfo(request)
        return render(request, 'HostGroupManage.html', {'user_info': user_info})

    def post(self, request, wid):
        user_info = GetUserInfo(request)
        return render(request, 'HostGroupManage.html', {'user_info': user_info})