import logging

import azure.functions as func
import requests
from os import getenv
import numpy as np
from PIL import Image
import io
import cv2
from datetime import datetime
import uuid
from bunch import Bunch
import json
from azureml.core import Workspace, Webservice
from azureml.core.authentication import ServicePrincipalAuthentication
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

url = getenv('URL')
headers = {'X-API-Key': getenv('API_KEY')}

sp = ServicePrincipalAuthentication(
    tenant_id=getenv('TENANT_ID'),
    service_principal_id=getenv('SP_ID'),
    service_principal_password=getenv('SP_PASSWD')
)

workspace = Workspace(
    subscription_id=getenv('SUB_ID'),
    resource_group=getenv('RESOURCE_GROUP'),
    workspace_name=getenv('WORKSPACE_NAME'),
    auth=sp
)

service = Webservice(workspace=workspace, name='aks-standing-laying-test1')
scoring_uri = service.scoring_uri

standing_scan_type = ["101", "102", "100"]
laying_scan_type = ["201", "202", "200"]

s = requests.Session()

retries = Retry(total=5,
                backoff_factor=0.1,
                status_forcelist=[ 500, 502, 503, 504 ],
                method_whitelist=frozenset(['GET', 'POST']))

s.mount('http://', HTTPAdapter(max_retries=retries))
s.mount('https://', HTTPAdapter(max_retries=retries))


def get_workflow_id(workflow_name, workflow_version):
    response = requests.get(url + f"/api/workflows", headers=headers)
    if response.status_code != 200:
        logging.info(f"error getting workflows {response.content}")
    workflows = response.json()['workflows']
    workflow = [workflow for workflow in workflows if workflow['name'] == workflow_name and workflow['version'] == workflow_version]

    return workflow[0]['id']


def orient_img(image, scan_type):
    # The images are rotated 90 degree clockwise for standing children
    # and 90 degree anticlock wise for laying children to make children
    # head at top and toe at bottom
    if scan_type in standing_scan_type:
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif scan_type in laying_scan_type:
        image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)

    return image


def standing_laying_data_preprocessing(file_id, scan_type):
    response = requests.get(url + f"/api/files/{file_id}", headers=headers)
    rgb_image = np.asarray(Image.open(io.BytesIO(response.content)))
    img = orient_img(rgb_image, scan_type)

    return img


def post_results(result_json_obj):
    """Post the result object produced while Result Generation using POST /results"""
    response = requests.post(url + '/api/results', json=result_json_obj, headers=headers)
    logging.info("%s %s", "Status of post result response:", response.status_code)
    return response.status_code


def prepare_result_object(rgb_artifacts, predictions, generated_timestamp, scan_id, workflow_id):
    """Prepare result object for results generated"""
    res = Bunch(dict(results=[]))
    for artifact, prediction in zip(rgb_artifacts, predictions):
        result = Bunch(dict(
            id=f"{uuid.uuid4()}",
            scan=scan_id,
            workflow=workflow_id,
            source_artifacts=[artifact['id']],
            source_results=[],
            generated=generated_timestamp,
            data={'standing': str(prediction[0])},
            start_time=artifact['standing_laying_start_time'],
            end_time=datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        ))
        res.results.append(result)
    return res


def bunch_object_to_json_object(bunch_object):
    """Convert given bunch object to json object"""
    json_string = json.dumps(bunch_object, indent=2, separators=(',', ':'))
    json_object = json.loads(json_string)
    return json_object


def post_result_object(rgb_artifacts, predictions, generated_timestamp, scan_id, workflow_id):
    """Post the result object to the API"""
    res = prepare_result_object(rgb_artifacts, predictions, generated_timestamp, scan_id, workflow_id)
    res_object = bunch_object_to_json_object(res)
    # print(res_object)
    if post_results(res_object) == 201:
        logging.info("%s %s", "successfully post Standing laying results:", res_object)


def get_standing_laying_prediction(img):
    data = {
         "data":img.tolist()
    }
    data = json.dumps(data)
    headers = {"Content-Type": "application/json"}
    response = s.post(scoring_uri, data=data, headers=headers)
    logging.info(f"predictions {response.content} and status code is {response.status_code}")
    predictions = response.json()

    return predictions    


def main(req: func.HttpRequest,
         context: func.Context) -> str:
    logging.info('Python HTTP trigger function processed a request.')
    response_object = {
        'invocation_id' : context.invocation_id,
        'operation_id' : context.trace_context.trace_parent.split('-')[1],
        'id' : context.trace_context.trace_parent.split('-')[2]
    }
    scan_metadata = req.params.get('scan_metadata')
    # standing_laying_workflow_id = req.params.get('standing_laying_workflow_id')
    if not scan_metadata:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            scan_metadata = req_body.get('scan_metadata')
            # standing_laying_workflow_id = req_body.get('standing_laying_workflow_id')
    try:
        if scan_metadata:
            standing_laying_workflow_id = get_workflow_id(getenv("STANDING_LAYING_WORKFLOW_NAME"), getenv("STANDING_LAYING_WORKFLOW_VERSION"))
            # response = requests.get(url + f"/api/scans?scan_id={scan_id}", headers=headers)
            # scan_metadata = response.json()['scans']
            # scan_version = scan_metadata[0]['version']
            scan_id = scan_metadata['id']
            scan_type = scan_metadata['type']
            logging.info(f"starting standing laying for scan id {scan_id}, {standing_laying_workflow_id}")
            rgb_artifacts = [a for a in scan_metadata['artifacts'] if a['format'] == 'rgb']
            predictions = []
            for rgb_artifact in rgb_artifacts:
                rgb_artifact['standing_laying_start_time'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
                img = standing_laying_data_preprocessing(rgb_artifact['file'], scan_type)
                prediction = get_standing_laying_prediction(img)
                predictions.append(prediction)
            predictions = np.array(predictions)
            # logging.info(f"predictions are {predictions}")
            generated_timestamp = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
            post_result_object(rgb_artifacts, predictions, generated_timestamp, scan_id, standing_laying_workflow_id)

            response_object["status"] = 'Success'
            logging.info(f"response object is {response_object}")
            return json.dumps(response_object)
        else:
            response_object["status"] = 'Failed'
            response_object["exception"] = 'scan metadata required'
            logging.info(f"response object is {response_object}")
            return json.dumps(response_object)
    except Exception as error:
        response_object["status"] = 'Failed'
        response_object["exception"] = str(error)
        logging.info(f"response object is {response_object}")
        return json.dumps(response_object)
