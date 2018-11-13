
from flask import render_template, url_for, session, redirect, request, flash
from app import webapp
import json
import boto3
from datetime import datetime, timedelta
from mysql.connector import connection

import boto3
import botocore

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
    util_for_add = 60.0
    util_for_remove = 20.0
    add_ratio = 2
    remove_ratio = 4

prev_instances = dict()
new_created_instances = []

@webapp.route('/')
def main():
    response = return_info()

    #print(response)
    #register_instance("i-0f579be0036a5fd77")
    #check if newly created instance finish bootup
    # for id in new_created_instances:
    #     if check_status(id):
    #         print("instance id %s is ready"%id)
    #         #register to load balancer
    #         register_instance(id)
    #         new_created_instances.pop(id)
    #
    #     else:
    #         print("instance id %s still booting"%id)


    return render_template("main.html", instance_info = response, params = ScalingParams)

@webapp.route('/update_params', methods=["POST"])
def update_params():
    if(request.method == 'POST'):
        if(request.form):
            try:
                ScalingParams.util_for_add = float(request.form.get("util_for_add"))
                ScalingParams.util_for_remove= float(request.form.get("util_for_remove"))
                ScalingParams.add_ratio = int(request.form.get("add_ratio"))
                ScalingParams.remove_ratio = int(request.form.get("remove_ratio"))
            except:
                flash("You have entered an invalid parameter.")
    return redirect('/')


@webapp.route('/add/<num>', methods=['POST'])
def add_instances(num):
    # get the largest worker name
    largest_worker = 0
    for key, value in prev_instances.items():
        curr_worker = int(value.name.split('_')[-1])
        if curr_worker > largest_worker:
            largest_worker = curr_worker

    #next worker number should be largest worker + 1
    largest_worker+=1

    for i in range(int(num)):
        new_id = create_instance(largest_worker+i)
        if(new_id == None):
            #TODO: handle create instance failure
            flash("create instance failed")
            return redirect("/")
        new_created_instances.append(new_id)
    flash("Created %d instances. "%len(new_created_instances))
    return redirect("/")

@webapp.route('/remove/<num>', methods=['POST'])
def delete_instances(num):
    num_int = 0
    try:
        num_int= int(num)
    except:
        flash("Must be int")
        return "/"
    print("%d, %d"%(num_int, len(prev_instances)))
    if num_int > len(prev_instances):
        flash("Trying to delete more instances than available")
        return redirect('/')

    for i in range(num_int):
        # get the largest worker name
        largest_worker = 0
        largest_worker_id = ""
        for key, value in prev_instances.items():
            curr_worker = int(value.name.split('_')[-1])
            if curr_worker > largest_worker:
                largest_worker = curr_worker
                largest_worker_id = key

        deregister_instance(largest_worker_id)
        terminate_instance(largest_worker_id)
        prev_instances.pop(largest_worker_id)

    flash("Deleted %d instances"%num_int)
    return redirect("/")




@webapp.route('/delete_all_data', methods=["POST"])
def delete_all_data():
    cnx = connection.MySQLConnection(user='photo_db_user', password='photo_db',
                                     host='54.208.46.115',
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
            inst_to_update.state_code = state[1]["Name"]
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
        StartTime=datetime.utcnow() - timedelta(seconds=60),
        EndTime=datetime.utcnow(),
        Period=60,
        Statistics=[
            'Average',
        ],
        Unit='Percent'
    )
    #print(response)

    for k, v in response.items():
        if k == 'Datapoints':
            for y in v:
                #print(y['Average'])
                return y['Average']

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
        ImageId='ami-019ac29ec54506d79',
        MinCount=1,
        MaxCount=1,
        KeyName="a2_1779",
        #SecurityGroups=[
        #    'launch-wizard-2',
        #],
        Monitoring={
            'Enabled': True
        },
        UserData=user_data_script,
        SubnetId='subnet-6c951b30',
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
        InstanceType='t2.micro')
    if instance is None or len(instance) == 0:
        return None
    new_instance_id = instance[0].id

    #print("instance: "+ new_instance_id + " is created.")
    #print("instance: "+ new_instance_id + " is starting...")
    instance[0].modify_attribute(Groups=['sg-0cda2de92a6fd6f4a'])
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