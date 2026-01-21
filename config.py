import os
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class Config:
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'

    # 文件存储配置
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    OUTPUT_FOLDER = os.path.join(BASE_DIR, 'static', 'outputs')

    # 确保目录存在
    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
        os.makedirs(folder, exist_ok=True)

    # 允许的文件类型
    ALLOWED_EXTENSIONS = {'pdf'}

    # API配置
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

    # 字体配置
    DEFAULT_FONT_MAPPING = {
        "Calibri": "Helvetica",
        "Calibri,Bold": "Helvetica-Bold",
        "Calibri,Italic": "Helvetica-Oblique",
        "Roboto-Regular": "Helvetica",
        "Roboto-Bold": "Helvetica-Bold",
        "Arial": "Helvetica",
        "Arial-Bold": "Helvetica-Bold",
        "Arial-Italic": "Helvetica-Oblique",
        "Arial-BoldItalic": "Helvetica-BoldOblique",
        "TimesNewRoman": "Times-Roman",
        "TimesNewRoman,Bold": "Times-Bold",
        "宋体": "Helvetica",
        "黑体": "Helvetica-Bold",
        "微软雅黑": "Helvetica",
        "SimSun": "Helvetica",
        "SimHei": "Helvetica-Bold"
    }

    # OSS配置
    OSS_ENDPOINT = os.environ.get('OSS_ENDPOINT', 'https://oss-cn-hangzhou.aliyuncs.com')
    OSS_ACCESS_KEY_ID = os.environ.get('OSS_ACCESS_KEY_ID')
    OSS_ACCESS_KEY_SECRET = os.environ.get('OSS_ACCESS_KEY_SECRET')
    OSS_BUCKET_NAME = os.environ.get('OSS_BUCKET_NAME', 'pdf-form-filler')
    OSS_PREFIX = os.environ.get('OSS_PREFIX', 'pdf/')

    # 应用URL配置
    BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000')

    @staticmethod
    def get_output_filename(pdf_name):
        """生成唯一的输出文件名"""
        if pdf_name:
            return f"{pdf_name}.pdf"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            return f"replaced_{timestamp}.pdf"

    @staticmethod
    def get_upload_filename():
        """生成唯一的上传文件名"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"upload_{timestamp}.pdf"