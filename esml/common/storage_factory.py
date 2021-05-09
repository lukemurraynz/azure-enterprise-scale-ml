"""
Copyright (C) Microsoft Corporation. All rights reserved.​
 ​
Microsoft Corporation (“Microsoft”) grants you a nonexclusive, perpetual,
royalty-free right to use, copy, and modify the software code provided by us
("Software Code"). You may not sublicense the Software Code or any use of it
(except to your affiliates and to vendors to perform work on your behalf)
through distribution, network access, service agreement, lease, rental, or
otherwise. This license does not purport to express any claim of ownership over
data you may have shared with Microsoft in the creation of the Software Code.
Unless applicable law gives you more rights, Microsoft reserves all other
rights not expressly granted herein, whether by implication, estoppel or
otherwise. ​
 ​
THE SOFTWARE CODE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
MICROSOFT OR ITS LICENSORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THE SOFTWARE CODE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""
from azureml.core import Datastore
#from azureml.core import Dataset
from  azureml.data.dataset_factory import FileDatasetFactory
import json
import sys
import os
sys.path.append(os.path.abspath("."))  # NOQA: E402
from baselayer_azure import AzureBase
from pathlib import Path

#import repackage
#repackage.up()


class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

#class LakeAccess(metaclass=Singleton):
class LakeAccess():

    ws = None
    storage_config = None
    suppress_logging = False
    datastore = None
    service_client = None # WRITE to adls gen 2
    project = None

    def __init__(self,ws, esml_project):  # **datasetNameKey_PathValue
        self.ws = ws
        self.project = esml_project
        self.suppress_logging = esml_project._suppress_logging
        self.ReloadConfiguration()
    
    def ReloadConfiguration(self): # overwrite = True
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            user_settings = ""
            if(self.project.demo_mode == False):
                user_settings = "../../"

            with open("{}../settings/project_specific/security_config.json".format(user_settings)) as f:
                self.storage_config = json.load(f)
        except Exception as e:
            print(e)
            print("LakeAccess.ReloadConfiguration - could not open security_config.json ")
        finally: 
            os.chdir(old_loc)

# ACL vs RBAC - https://docs.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-access-control-model
    def GetLakeAsDatastore(self, setAsDefault=False):
        datastore_name = self.storage_config['lake_datastore_name']

        sp_id_key = self.storage_config['kv-secret-esml-projectXXX-sp-id']
        sp_secret_key = self.storage_config['kv-secret-esml-projectXXX-sp-secret']
        tenant = self.storage_config['tenant']
        url = self.storage_config['external_keyvault_url']

        if(self.suppress_logging==False):
            print("GetLakeAsDatastore: ws.name", self.ws.name)
            print("GetLakeAsDatastore: tenant", tenant)
            print("GetLakeAsDatastore: sp_id_key", sp_id_key)
            print("GetLakeAsDatastore: sp_secret_key", sp_secret_key)
            print("GetLakeAsDatastore: get_external_keyvault", url)

        external_kv, tenantId = AzureBase.get_external_keyvault(self.ws, sp_id_key, sp_secret_key, tenant, url)
        lake_name = self.storage_config['lake_name']
        file_system_name = self.storage_config['lake_fs']

        if(self.suppress_logging==False):
            print("Register ES-ML lake as Datastore, as {}".format(datastore_name))

        # 1) API to WRITE
        secret_bundle1 = external_kv.get_secret(self.storage_config['esml-common-sp-id'], "")
        secret_bundle2 = external_kv.get_secret(self.storage_config['esml-common-sp-secret'], "")
        self.service_client = AzureBase.initialize_storage_account_ad(lake_name, secret_bundle1.value, secret_bundle2.value, tenantId)
        
        try:
            ds = Datastore(self.ws, datastore_name)  # Return if already exists
            self.datastore = ds
            if(ds != None):
                return ds
        except Exception as ex:
            print("Datastore to common lake does not exists in AMLS workspace {}, creating it...{}".format(self.ws.name, datastore_name))
            print(ex)
        
        #2 API to READ 
        datastore = Datastore.register_azure_data_lake_gen2(workspace=self.ws,
                                                            datastore_name=datastore_name,
                                                            filesystem=file_system_name,
                                                            account_name=lake_name,
                                                            tenant_id=tenantId,
                                                            client_id=secret_bundle1.value,
                                                            client_secret=secret_bundle2.value,
                                                            grant_workspace_access=True,
                                                            skip_validation=True)
        if(setAsDefault):
            self.ws.set_default_datastore(datastore)
        self.datastore = datastore

        return datastore

    def GetBlobAsDatastore(self,setAsDefault=False):
        datastore_name = self.storage_config['blob_datastore_name']
        if(self.suppress_logging==False):
            print("Register ES-ML BLOB as Datastore, as {}".format(datastore_name))
        
        #if (self.project.RecreateDatastore):
        try:
            ds = Datastore(self.ws, datastore_name)  # Return if already exists
            self.datastore = ds
            return ds
        except:
            print("No datastore with name {} exists, creating one...".format(datastore_name))
    
        account_name = self.storage_config['temp_blob_name']
        container_name = self.storage_config['lake_fs']

        #2 Get SECRET from KeyVault - accesst to TEMP storage account
        keyvault = self.ws.get_default_keyvault()
        temp_blob_secret_key = self.storage_config['temp_blob_secret_key']
        saKey = keyvault.get_secret(name=temp_blob_secret_key)


        datastore = Datastore.register_azure_blob_container(workspace=self.ws,
                                                            datastore_name=datastore_name,  # ....usually =  my_blob_name
                                                            container_name=container_name,  # = data_store
                                                            account_name=account_name,
                                                            account_key=saKey,
                                                            create_if_not_exists=False,
                                                            grant_workspace_access=True,
                                                            skip_validation=True)
        if(setAsDefault):
            self.ws.set_default_datastore(datastore)
        self.datastore = datastore
        return datastore

    def upload(self, file_name, local_folder_path, bronze_silver_gold_target_path,overwrite=True,use_dataset_factory = True):

        storage_type_blob = self.storage_config["storage_type_blob"] # BLOB vs GEN2 # BLOB vs GEN2
        data_folder = Path(local_folder_path) # path only to folder
        local_file_fullpath = data_folder / file_name # Full filename

        # BLOB
        if(storage_type_blob):
            self.datastore.upload(src_dir=local_folder_path, target_path=bronze_silver_gold_target_path, overwrite=overwrite) # BLOB
        else: # GEN 2 (2 options)
            use_dataset_factory = False
            if(use_dataset_factory):  # GEN 2 Alt 1: from  azureml.data.dataset_factory import FileDatasetFactory
                self.upload2_exp(local_folder_path, bronze_silver_gold_target_path,overwrite)  
            else: # GEN 2 Alt 2:  from azure.storage.filedatalake import DataLakeServiceClient
                filesystem = self.storage_config['lake_fs']
                AzureBase.upload_file_to_directory(self.service_client, filesystem,file_name, local_file_fullpath, bronze_silver_gold_target_path,overwrite)

    def upload2_exp(self, local_parent_folder, bronze_silver_gold_target_path,overwrite=True):
        #print("Uploading to datastore: {} ".format(self.datastore))
        #print("From: {} ".format(local_parent_folder))
        #print("To: {} ".format(bronze_silver_gold_target_path))
        FileDatasetFactory.upload_directory(src_dir=local_parent_folder, target=(self.datastore, bronze_silver_gold_target_path), pattern=None, overwrite=overwrite, show_progress=False)
        #Dataset.File.upload_directory(src_dir=”./local/data”, target=(adlsgen2_datastore, path))

