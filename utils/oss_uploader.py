import os
import oss2
from datetime import datetime
from config import Config


class OSSUploader:
    def __init__(self):
        """
        初始化OSS上传器
        """
        self.endpoint = Config.OSS_ENDPOINT
        self.access_key_id = Config.OSS_ACCESS_KEY_ID
        self.access_key_secret = Config.OSS_ACCESS_KEY_SECRET
        self.bucket_name = Config.OSS_BUCKET_NAME
        self.prefix = Config.OSS_PREFIX

        # 检查OSS配置
        if not all([self.access_key_id, self.access_key_secret, self.bucket_name]):
            print("警告: OSS配置不完整，将使用本地存储")
            self.enabled = False
        else:
            self.enabled = True
            self._init_oss_client()

    def _init_oss_client(self):
        """初始化OSS客户端"""
        try:
            auth = oss2.Auth(self.access_key_id, self.access_key_secret)
            self.bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)
            print("OSS客户端初始化成功")
        except Exception as e:
            print(f"OSS客户端初始化失败: {e}")
            self.enabled = False

    def upload_to_oss(self, filepath: str, customer_code: str, order_no: str) -> str:
        """
        上传文件到OSS

        Args:
            filepath: 本地文件路径

        Returns:
            str: OSS访问URL
            :param filepath:
            :param order_no:
            :param customer_code:
        """
        if not self.enabled:
            # 返回本地URL
            base_url = Config.BASE_URL
            filename = os.path.basename(filepath)
            return f"{base_url}/static/outputs/{filename}"

        try:
            # 生成OSS对象名
            timestamp = datetime.now().strftime("%Y/%m/%d")
            filename = os.path.basename(filepath)
            object_name = f"{self.prefix}{customer_code}/{order_no}/{filename}"

            # 上传文件
            result = self.bucket.put_object_from_file(object_name, filepath)

            if result.status == 200:
                # 生成访问URL
                if self.endpoint.startswith('https://'):
                    url = f"https://{self.bucket_name}.{self.endpoint[8:]}/{object_name}"
                else:
                    url = f"https://{self.bucket_name}.{self.endpoint}/{object_name}"

                print(f"文件上传到OSS成功: {url}")
                return url
            else:
                raise Exception(f"OSS上传失败，状态码: {result.status}")

        except Exception as e:
            print(f"OSS上传失败，使用本地存储: {e}")
            # 上传失败时返回本地URL
            base_url = Config.BASE_URL
            filename = os.path.basename(filepath)
            return f"{base_url}/static/outputs/{filename}"