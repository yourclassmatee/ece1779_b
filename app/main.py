
from flask import render_template, url_for, session, redirect, request, flash, send_from_directory
from app import webapp
import json
import boto3
from datetime import datetime, timedelta
from mysql.connector import connection
from math import *
import boto3
from statistics import mean

BUCKET = 'photos-ece1779-a2'
ARN = "arn:aws:elasticloadbalancing:us-east-1:824599980641:targetgroup/a2workers/300f86a44db73bce"

class InstanceInfo:
    id = ""
    name = ""
    state_code = 0
    state_name = ""
    status2_2 = False
    health_check_status = ""
    cpu_util = 0

class ScalingParams:
    enabled = False
    util_for_add = 60.0
    util_for_remove = 0.1
    add_ratio = 2
    remove_ratio = 4

prev_instances = dict()
new_created_instances = []

@webapp.route('/')
def main():
    if session.get('admin') is None or session['admin'] != webapp.config['ROOT_USER']:
        flash("You are not logged in!")
        return redirect('/login')

    response = return_info()
    for id,inst in response.items():
        if inst.state_name != "terminated":
            get_cpu_graph(id, inst.name)
    return render_template("main.html", instance_info = response, params = ScalingParams)

@webapp.route('/update_params', methods=["POST"])
def update_params():
    if session.get('admin') is None or session['admin'] != webapp.config['ROOT_USER'] :
        flash("You are not logged in!")
        return redirect('/login')

    if request.method == 'POST':
        if request.form:
            try:
                if float(request.form.get("util_for_add")) < float(request.form.get("util_for_remove")):
                    flash("Cpu threashold for growing should be larger then for shrinking")
                    return redirect("/")
                if int(request.form.get("add_ratio")) < 1 or int(request.form.get("remove_ratio")) < 1:
                    flash("Ratios should be larger than 1")
                    return redirect("/")
                ScalingParams.util_for_add = float(request.form.get("util_for_add"))
                ScalingParams.util_for_remove= float(request.form.get("util_for_remove"))
                ScalingParams.add_ratio = int(request.form.get("add_ratio"))
                ScalingParams.remove_ratio = int(request.form.get("remove_ratio"))

                if request.form.get("auto_scaling") == "on":
                    ScalingParams.enabled = True
                else:
                    ScalingParams.enabled = False
                #print("=====================%s"%str(ScalingParams.enabled))
            except:
                flash("You have entered an invalid parameter.")
                return redirect('/')
            flash("Auto scaling parameters are updated")
    return redirect('/')


@webapp.route('/add/<num>', methods=['POST'])
def add_instances(num):
    if session.get('admin') is None or session['admin'] != webapp.config['ROOT_USER']:
        flash("You are not logged in!")
        return redirect('/login')
    result = do_add_instance(num)
    if result == False:
        flash("Create instance failed")
    else:
        flash("Created %d instances. "%len(new_created_instances))
    return redirect('/')

def do_add_instance(num):
    # get the largest worker name
    largest_worker = 0
    instances = list_instances()
    for key, value in instances.items():
        curr_worker = int(value[0].split('_')[-1])
        if curr_worker > largest_worker:
            largest_worker = curr_worker

    #next worker number should be largest worker + 1
    largest_worker+=1

    for i in range(int(num)):
        new_id = create_instance(largest_worker+i)
        if new_id is not None:
            new_created_instances.append(new_id)
            print("Created instance %s"%new_id)
        else:
            print("Create instance failed")
            return False
    return True

@webapp.route('/remove/<num>', methods=['POST'])
def delete_instances(num):
    if session.get('admin') is None or session['admin'] != webapp.config['ROOT_USER']:
        flash("You are not logged in!")
        return redirect('/login')
    num_int = 0
    try:
        num_int = int(num)
    except:
        flash("Instance number must be int")
        return "/"
    result = do_delete_instance(num_int)
    if result:
        flash("Deleted %s instances"%num)
    else:
        flash("Trying to delete more instances than available")
    return redirect('/')


def do_delete_instance(num_int):
    all_instances = list_instances()
    healthy_instances = 0
    for key in all_instances.keys():
        if health_check(key) == "healthy":
            healthy_instances += 1

    if num_int >= healthy_instances:
        print("Trying to delete more instances than available")
        return False

    for i in range(num_int):
        # get the largest worker name
        largest_worker = -1
        largest_worker_id = ""
        for key, value in all_instances.items():
            if health_check(key) == "healthy":
                curr_worker = int(value[0].split('_')[-1])
                if curr_worker > largest_worker:
                    largest_worker = curr_worker
                    largest_worker_id = key
        if largest_worker != -1:
            deregister_instance(largest_worker_id)
            terminate_instance(largest_worker_id)
        print("deleting instance id %s" % largest_worker_id)
        #prev_instances.pop(largest_worker_id)

    return True




@webapp.route('/delete_all_data', methods=["POST"])
def delete_all_data():
    if session.get('admin') is None or session['admin'] != webapp.config['ROOT_USER']:
        flash("You are not logged in!")
        return redirect('/login')

    cnx = connection.MySQLConnection(user='photo_db_user', password='photo_db',
                                     host='18.208.110.40',
                                     database='photo_db')
    cursor = cnx.cursor()
    query = "DELETE FROM photo"
    cursor.execute(query)
    photos_del = cursor.rowcount

    query = "DELETE FROM user"
    cursor.execute(query)
    users_del = cursor.rowcount

    cursor.close()
    cnx.commit()
    cnx.close()


    #delete all from s3
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(BUCKET)
    # suggested by Jordon Philips
    bucket.objects.all().delete()

    flash("deleted %d users, %d photos from db"%(users_del,photos_del))
    return redirect('/')

@webapp.route('/get_cpu_graph/<id>', methods=["GET"])
def get_graph(id):
    if session.get('admin') is None or session['admin'] != webapp.config['ROOT_USER']:
        flash("You are not logged in!")
        return redirect('/login')

    #print("getting graph")
    return send_from_directory(webapp.config['UPLOAD_FOLDER'], id+".png",cache_timeout=1, last_modified = datetime.now())

@webapp.route('/get_cpu_ajax', methods=['GET'])
def get_cpu_ajax():
    cpu_util = {}
    for id, inst in prev_instances.items():
        if inst.state_name != "terminated":
            cpu_util[id] = get_cpu(id)
    return json.dumps(cpu_util)



def return_info():
    instance_infos = []
    #print("=================================================")
    instances = list_instances()
    #print(instances)
    for id, state in instances.items():
        #existing instance, update
        if id in prev_instances.keys():
            inst_to_update = prev_instances[id]
            #update state and cpu util
            inst_to_update.state_code = state[1]["Code"]
            inst_to_update.state_name = state[1]["Name"]
            new_util = get_cpu(id)
            if new_util is not None:
                inst_to_update.cpu_util = new_util
            inst_to_update.status2_2 = check_status(id)
            inst_to_update.health_check_status = health_check(id)
        #add new instances
        else:
            info = InstanceInfo()
            info.id = id
            info.name = state[0]
            info.state_code = state[1]["Code"]
            info.state_name = state[1]["Name"]
            info.cpu_util = get_cpu(id)
            if info.cpu_util is None:
                info.cpu_util = 0
            info.status2_2 = check_status(info.id)
            info.health_check_status = health_check(info.id)
            prev_instances[id] = info
            # remove if not in newly fetched instances
    for key in list(prev_instances.keys()):
        key_still_exist = False
        for id in instances.keys():
            if id == key:
                key_still_exist = True
                break
        if key_still_exist == False:
            del prev_instances[key]
    return prev_instances


def auto_scaling():
    # check newly created instance's status if the list is not empty
    if len(new_created_instances) > 0:
        for id in new_created_instances:
            if check_status(id):
                print("auto-scaling: new instance id %s is ready"%id)
                #register to load balancer
                register_instance(id)
                new_created_instances.remove(id)
        return

    if not ScalingParams.enabled:
        print("auto-scaling: off")
        return

    all_instances= list_instances()
    # otherwise, check CPU
    cpu_utils=[]
    current_healthy_instance_num=0

    for key in all_instances.keys():
        if health_check(key) == 'healthy':
            current_healthy_instance_num += 1
            cpu_util=get_cpu(key)
            if cpu_util is not None:
                cpu_utils.append(cpu_util)

    avg_cpu=mean(cpu_utils)
    if avg_cpu > ScalingParams.util_for_add:
        create_instance_num = current_healthy_instance_num * (ScalingParams.add_ratio - 1)
        print("auto-scaling: avg cpu %f, add %d new instances" %(avg_cpu,create_instance_num))
        do_add_instance(create_instance_num)
    elif avg_cpu < ScalingParams.util_for_remove:
        terminate_instance_num = floor(current_healthy_instance_num - current_healthy_instance_num / ScalingParams.remove_ratio)
        print("auto-scaling: avg cpu %f, remove %d instances" %(avg_cpu,terminate_instance_num))
        do_delete_instance(terminate_instance_num)
    else:
        print("auto-scaling: avg cpu %f, do nothing"%avg_cpu)

    # larger_than_add_threshold=[x for x in cpu_utils if x >= ScalingParams.util_for_add]
    # less_than_add_threshold = [x for x in cpu_utils if x <= ScalingParams.util_for_remove]
    # print("current healthy instance %d"%current_healthy_instance_num)
    # print("len(cup_util) %d"%len(cpu_utils))
    # print("larger than %d: "%ScalingParams.util_for_add)
    # print(larger_than_add_threshold)
    # print("less than %d: "%ScalingParams.util_for_remove)
    # print(less_than_add_threshold)
    # if len(larger_than_add_threshold) == len(less_than_add_threshold) :
    #     print("auto-scaling: tie, do nothing")
    #     return # do nothing
    # elif len(larger_than_add_threshold) >= len(cpu_utils)/2 :
    #     if ScalingParams.add_ratio <= 1 :
    #         print("auto-scaling: Expand working pool decision made by auto scaling policy. But scaling ratio <= 1, can't create new instances by policy")
    #         return
    #     create_instance_num = current_healthy_instance_num * (ScalingParams.add_ratio-1)
    #     print("auto-scaling: add %d new instances"%create_instance_num)
    #     do_add_instance(create_instance_num)
    # elif len(less_than_add_threshold) >= len(cpu_utils)/2 :
    #     if ScalingParams.remove_ratio <= 1 :
    #         print("Shrink working pool decision made by auto scaling policy. But scaling ratio <= 1, can't create new instances by policy")
    #         return
    #     terminate_instance_num= floor(current_healthy_instance_num - current_healthy_instance_num / ScalingParams.remove_ratio)
    #     print("auto-scaling: remove %d instances"%terminate_instance_num)
    #     do_delete_instance(terminate_instance_num)
    # else:
    #     print("auto-scaling: do nothing")


#==================================functions that interact with aws============================================

def list_instances():
    ec2 = boto3.resource('ec2')
    instances = dict()
    #return len(ec2.instances)
    for instance in ec2.instances.all():
        #print(instance.id)
        instance_name = ''
        if instance.tags is None:
            continue
        for tags in instance.tags:
            if tags["Key"] == 'Name':
                instance_name = tags["Value"]
                #print(instance_name)
        if "worker" in instance_name:
            instances[instance.id] = (instance_name, instance.state)
    return instances


def get_cpu(instance_id):
    client = boto3.client('cloudwatch')
    response = client.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='CPUUtilization',
        Dimensions=[
            {
            'Name': 'InstanceId',
            'Value': instance_id # instance id
            },
        ],
        StartTime=datetime.utcnow() - timedelta(seconds=120),#60
        EndTime=datetime.utcnow(),
        Period=60,
        Statistics=[
            'Average',
        ],
        Unit='Percent'
    )
    #print(instance_id)
    #print(response)

    for k, v in response.items():
        if k == 'Datapoints':
            if len(v) == 0:
                #print("no data point")
                return None
            elif len(v) == 1:
                #print("only 1 data point, "+str(v[0]['Average']))
                return v[0]['Average']
            elif v[0]['Timestamp'] < v[1]['Timestamp']:
                #print("2 data points, use "+str(v[1]['Average']))
                return v[1]['Average']
            elif v[0]['Timestamp'] > v[1]['Timestamp']:
                #print("2 data points, use "+str(v[0]['Average']))
                return v[0]['Average']


def get_cpu_graph(instance_id, worker_name):
    client = boto3.client('cloudwatch')
    metric_json = json.dumps(
            {
                "width": 300,
                "height": 200,
                "period":300,
                "start":"-PT1H",
                "end":"PT0H",
                "timezone": '-0500',
                "view": "timeSeries",
                "stacked": False,
                "stat": "Average",
                "title": worker_name,
                "metrics": [[ "AWS/EC2", "CPUUtilization", "InstanceId", instance_id ]],

            }
        )
    response = client.get_metric_widget_image(
        MetricWidget=metric_json,
    )
    image = {'file': response['MetricWidgetImage']}
    path =webapp.config['UPLOAD_FOLDER'] + instance_id + ".png"
    file = open(path, "wb")

    file.write(image["file"])

    file.close()


def create_instance(worker_num):
    #print("+++++++++++++++++++++++++++++++creating worker number %d"%worker_num)

    user_data_script = """#!/bin/bash
    cd /home/ubuntu/proj2
    . venv/bin/activate
    export FLASK_CONFIG=development
    export FLASK_APP=run.py
    python run.py"""

    ec2 = boto3.resource('ec2')
    instance = ec2.create_instances(
        ImageId='ami-06349291ec46d10f3',
        MinCount=1,
        MaxCount=1,
        KeyName="a2_1779",
        SecurityGroups=[
            'launch-wizard-2',
        ],
        Monitoring={
            'Enabled': True
        },
        #UserData=user_data_script,
        #SubnetId='subnet-6c951b30',
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [
                    {
                        'Key': 'Name',
                        'Value': "worker_"+str(worker_num)
                    },
                ]
            },
        ],
        InstanceType='t2.small')
    if instance is None or len(instance) == 0:
        return None
    new_instance_id = instance[0].id

    #print("instance: "+ new_instance_id + " is created.")
    #print("instance: "+ new_instance_id + " is starting...")
    #instance[0].modify_attribute(Groups=['sg-0cda2de92a6fd6f4a'])
    return new_instance_id


def check_status(instance_id):
    client = boto3.client('ec2')
    rsp = client.describe_instance_status(
        InstanceIds=[str(instance_id)],
        IncludeAllInstances=True
    )
    # check status
    instance_status = rsp['InstanceStatuses'][0]['InstanceStatus']['Status']
    system_status = rsp['InstanceStatuses'][0]['SystemStatus']['Status']

    if str(instance_status) == 'ok' and str(system_status) == 'ok':
        return True
    return False

def register_instance(instance_id):
    client = boto3.client('elbv2')
    response = client.register_targets(
        TargetGroupArn=ARN,
        Targets=[
            {
                'Id': instance_id,
            },
        ],
    )

def deregister_instance(instance_id):
    client = boto3.client('elbv2')
    response = client.deregister_targets(
        TargetGroupArn=ARN,
        Targets=[
            {
                'Id': instance_id,
            },
        ],
    )

def terminate_instance(instance_id):
    client = boto3.client("ec2")
    response = client.terminate_instances(
        InstanceIds=[
            instance_id,
        ],
    )




def health_check(instance_id):
    client = boto3.client('elbv2')
    response = client.describe_target_health(
        TargetGroupArn=ARN,
        Targets = [{
            'Id' : instance_id,
        },
    ],
    )
    return response["TargetHealthDescriptions"][0]["TargetHealth"]["State"]