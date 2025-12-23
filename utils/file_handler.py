import os
import requests
import uuid
from urllib.parse import urlparse
import fitz
from config import Config


class FileHandler:
    @staticmethod
    def download_pdf_from_url(url, save_dir=Config.UPLOAD_FOLDER):
        """
        从URL下载PDF文件

        Args:
            url: PDF文件的网络URL
            save_dir: 保存目录

        Returns:
            str: 本地文件路径
        """
        try:
            # 验证URL
            parsed_url = urlparse(url)
            if not parsed_url.scheme in ('http', 'https'):
                raise ValueError("无效的URL格式")

            # 下载文件
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            # 生成唯一文件名
            filename = f"temp_{uuid.uuid4().hex}.pdf"
            filepath = os.path.join(save_dir, filename)

            # 保存文件
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # 验证文件是否为有效的PDF
            try:
                doc = fitz.open(filepath)
                doc.close()
            except:
                os.remove(filepath)
                raise ValueError("下载的文件不是有效的PDF格式")

            return filepath

        except requests.exceptions.RequestException as e:
            raise Exception(f"下载PDF失败: {str(e)}")
        except Exception as e:
            raise Exception(f"处理PDF失败: {str(e)}")

    @staticmethod
    def save_output_pdf(filepath, output_dir=Config.OUTPUT_FOLDER):
        """
        保存输出PDF并返回访问URL

        Args:
            filepath: 本地文件路径
            output_dir: 输出目录

        Returns:
            tuple: (文件路径, 访问URL)
        """
        # 生成输出文件名
        output_filename = Config.get_output_filename()
        output_path = os.path.join(output_dir, output_filename)

        # 复制文件到输出目录
        import shutil
        shutil.copy2(filepath, output_path)

        # 生成访问URL
        base_url = os.environ.get('BASE_URL', 'http://localhost:5000')
        access_url = f"{base_url}/static/outputs/{output_filename}"

        return output_path, access_url

    @staticmethod
    def cleanup_files(*filepaths):
        """
        清理临时文件

        Args:
            *filepaths: 要删除的文件路径列表
        """
        for filepath in filepaths:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                print(f"删除文件 {filepath} 失败: {e}")

    @staticmethod
    def is_allowed_file(filename):
        """
        检查文件类型是否允许

        Args:
            filename: 文件名

        Returns:
            bool: 是否允许
        """
        return '.' in filename and \
            filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS