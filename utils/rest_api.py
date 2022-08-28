from os import getenv
import requests
import datetime
from typing import Dict


class RestApi:
    def __init__(self, base_url: str, api_key: str):
        self.url = base_url
        self.headers = {'X-API-Key': api_key}

    def __get(self, path: str, params: Dict = None):
        resp = requests.get(self.url + path, headers=self.headers, params=params)
        resp.raise_for_status()
        return resp

    def get_json(self, path: str, params=None):
        return self.__get(path, params).json()

    def get_binary(self, path: str, params=None):
        return self.__get(path, params).content

    def post_json(self, path, json):
        resp = requests.post(self.url + path, headers=self.headers, json=json)
        resp.raise_for_status()
        return resp.json()

    def put_json(self, path, json):
        resp = requests.put(self.url + path, headers=self.headers, json=json)
        resp.raise_for_status()
        return resp.json()

    def post_binary(self, path, files):
        resp = requests.post(self.url + path, headers=self.headers, files=files)
        resp.raise_for_status()
        return resp.content


class MlApi(RestApi):
    def __init__(self):
        super().__init__(getenv("APP_URL"),getenv("API_KEY"))

    def get_files(self, file_id):
        return self.get_binary(f"/api/files/{file_id}")

    def get_basic_person_info(self, person_id):
        basic_info = self.get_json(f'/api/persons/{person_id}/basic')
        return basic_info['date_of_birth'], basic_info['sex']

    def get_manual_measures(self, person_id, scan_date):
        manual_measures = self.get_json(f'/api/persons/{person_id}/measurement')['measurements']

        mm_keys_keys = ['height', 'weight', 'muac', 'head_cir', 'oedema' ,'location']
        mms = []
        for mm in manual_measures:
            if scan_date == datetime.datetime.strptime(mm['measured'], '%Y-%m-%dT%H:%M:%SZ').date():
                target_dict = dict((k, mm[k]) for k in mm_keys_keys if k in mm)
                mms.append(target_dict)
        return mms

    def get_scan_metadata(self, scan_id):
        return self.get_json(f"/api/scans/{scan_id}")['scan']

    def get_workflows(self):
        return self.get_json('/api/workflows')['workflows']

    def get_etl_packet(self, target_date):
        return self.get_json('/api/etl_packet', params={'target_date': target_date})
    
    def put_data_category(self, scan_data_category):
        self.put_json('/api/scans/assign_data_category', json=scan_data_category)

    def post_results(self, results):
        self.post_json('/api/results', json=results)

    def post_files(self, bin_file, file_format) -> str:
        if file_format == 'rgb':
            filename = 'test.jpg'
        elif file_format == 'depth':
            filename = 'test.depth'
        else:
            raise ValueError(f"Unrecognized file format: {file_format}.")

        files = {
            'file': bin_file,
            'filename': filename
        }
        return self.post_binary('/api/files', files=files).decode('utf-8')

    def get_workflow_id_and_service_name(self, workflow_name, workflow_version, get_service_name=False):
        workflows = self.get_workflows()
        workflow = [workflow for workflow in workflows if workflow['name'] == workflow_name and workflow['version'] == workflow_version]
        if get_service_name:
            return workflow[0]['id'], workflow[0]['data']['service_name']
        else:
            return workflow[0]['id']


    def get_results(self, scan_id, workflow_id):
        """Get Result from scan id and workflow id """
        params = {
            'workflow': workflow_id, 
            'show_results': True, 
            'scan_id': scan_id
        }
        return self.get_json('/api/scans', params=params)['scans'][0]['results']


class ErrorStatsApi(RestApi):
    def __init__(self):
        super().__init__(getenv("ERROR_STATS_URL"),getenv("ERROR_STATS_API_KEY"))

    def get_percentile_from_error_stats(self, params):
        """Get the scan metadata filtered by scan_version and workflow_id"""
        return self.get_json('/api/percentile_errors', params=params)
