import json
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify, render_template
import os
import fitz
from datetime import datetime
import concurrent.futures
from config import Config
from utils.file_handler import FileHandler
from utils.pdf_processor import PDFProcessor
from utils.oss_uploader import OSSUploader
import pandas as pd
import zipfile
from flask import send_file
import tempfile

# 初始化Flask应用
app = Flask(__name__, template_folder='templates')
app.config.from_object(Config)

# 初始化处理器
file_handler = FileHandler()
pdf_processor = PDFProcessor()
oss_uploader = OSSUploader()


@app.route('/')
def index():
    """首页 - 显示前端界面"""
    return render_template('index.html')


@app.route('/api/download-zip', methods=['POST'])
def download_zip():
    """
    批量下载PDF文件到ZIP压缩包

    请求参数:
    {
        "urls": ["http://example.com/file1.pdf", "http://example.com/file2.pdf"],
        "filename": "batch_files.zip"
    }
    """
    try:
        # 检查是否是JSON请求
        if request.is_json:
            request_data = request.get_json()
        else:
            # 如果不是JSON，尝试从表单数据获取
            request_data = {}
            if 'urls' in request.form:
                request_data['urls'] = json.loads(request.form['urls'])
            if 'filename' in request.form:
                request_data['filename'] = request.form['filename']

        if 'urls' not in request_data or not isinstance(request_data['urls'], list):
            return jsonify({
                "code": 400,
                "message": "缺少urls参数或格式错误",
                "data": None
            }), 400

        urls = request_data['urls']
        filename = request_data.get('filename', 'batch_files.zip')

        # 创建临时ZIP文件
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, filename)

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, url in enumerate(urls):
                try:
                    # 下载PDF文件
                    response = requests.get(url, timeout=30)
                    response.raise_for_status()

                    # 生成ZIP内的文件名
                    parsed_url = urlparse(url)
                    original_filename = os.path.basename(parsed_url.path)
                    if not original_filename or '.' not in original_filename:
                        original_filename = f"file_{i + 1}.pdf"

                    # 添加到ZIP
                    zipf.writestr(original_filename, response.content)
                except Exception as e:
                    # 如果某个文件下载失败，跳过并记录
                    print(f"下载文件失败 {url}: {str(e)}")
                    continue

        # 返回ZIP文件
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/zip'
        )

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"创建ZIP失败: {str(e)}",
            "data": None
        }), 500

@app.route('/api/fill-pdf', methods=['POST'])
def fill_pdf():
    """
    PDF表单填充API接口（支持批量）

    请求参数（JSON格式）:
    {
        "data": {
            "PO_NO": "PO20240001",
            "NAME": "张三",
            "DATE": "2024-01-01"
        },
        "font": "Helvetica",  # 可选，自定义字体
        "fontsize": 12,       # 可选，自定义字体大小
        "url": "http://example.com/document.pdf"  # 单文件
        "urls": [  # 或多文件
            "http://example.com/document1.pdf",
            "http://example.com/document2.pdf"
        ]
    }

    返回:
    {
        "code": 200,
        "message": "success",
        "data": {
            "files": [
                {
                    "original_url": "http://example.com/document1.pdf",
                    "processed_url": "https://oss.example.com/pdf/output1.pdf",
                    "filename": "output1.pdf"
                },
                {
                    "original_url": "http://example.com/document2.pdf",
                    "processed_url": "https://oss.example.com/pdf/output2.pdf",
                    "filename": "output2.pdf"
                }
            ],
            "total": 2,
            "batch_id": "batch_20240101120000"
        }
    }
    """
    try:
        # 获取请求数据
        if not request.is_json:
            return jsonify({
                "code": 400,
                "message": "请求必须是JSON格式",
                "data": None
            }), 400

        request_data = request.get_json()

        # 验证必需参数
        if 'data' not in request_data:
            return jsonify({
                "code": 400,
                "message": "缺少必需参数: data",
                "data": None
            }), 400

        # 提取参数
        data = request_data['data']
        custom_font = request_data.get('font')
        custom_fontsize = request_data.get('fontsize')
        customer_code = request_data.get('customer_code')
        order_no = request_data.get('order_no')

        # 获取PDF URL或URLs
        pdf_urls = []
        if 'url' in request_data:
            pdf_urls = [request_data['url']]
        elif 'urls' in request_data:
            pdf_urls = request_data['urls']
        else:
            return jsonify({
                "code": 400,
                "message": "缺少必需参数: url 或 urls",
                "data": None
            }), 400

        # 验证data参数
        if not data:
            return jsonify({
                "code": 400,
                "message": "data参数不能为空",
                "data": None
            }), 400

        # 处理单份或多份数据
        if isinstance(data, dict):
            data_list = [data]
        elif isinstance(data, list):
            data_list = data
        else:
            return jsonify({
                "code": 400,
                "message": "data参数必须是字典或字典列表",
                "data": None
            }), 400

        # 验证URLs
        for url in pdf_urls:
            if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
                return jsonify({
                    "code": 400,
                    "message": f"无效的URL格式: {url}",
                    "data": None
                }), 400

        # 批量处理PDF
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 限制最大处理数量
        max_files = 1000  # 可以调整
        if len(pdf_urls) * len(data_list) > max_files:
            return jsonify({
                "code": 400,
                "message": f"一次最多处理{max_files}个文件",
                "data": None
            }), 400

        # 处理结果
        processed_files = []
        errors = []

        # 使用线程池并发处理
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            # 为每个URL和每份数据创建任务
            future_to_pdf = {}

            for pdf_index, pdf_url in enumerate(pdf_urls):
                for data_index, data_item in enumerate(data_list):
                    # 创建唯一的任务标识
                    task_id = f"{batch_id}_pdf{pdf_index}_data{data_index}"

                    # 提交处理任务
                    future = executor.submit(
                        process_single_pdf_task,
                        pdf_url,
                        data_item,
                        custom_font,
                        custom_fontsize,
                        pdf_index,
                        data_index,
                        file_handler,
                        pdf_processor,
                        oss_uploader,
                        customer_code,
                        order_no
                    )
                    future_to_pdf[future] = {
                        'url': pdf_url,
                        'task_id': task_id,
                        'pdf_index': pdf_index,
                        'data_index': data_index
                    }

            # 收集结果
            for future in concurrent.futures.as_completed(future_to_pdf):
                task_info = future_to_pdf[future]
                try:
                    result = future.result()
                    if result['success']:
                        processed_files.append(result['file_info'])
                    else:
                        errors.append({
                            'url': task_info['url'],
                            'error': result['error']
                        })
                except Exception as e:
                    errors.append({
                        'url': task_info['url'],
                        'error': str(e)
                    })

        # 检查是否有成功处理的文件
        if not processed_files:
            return jsonify({
                "code": 500,
                "message": "所有文件处理失败",
                "data": {
                    "errors": errors
                }
            }), 500

        # 返回结果
        return jsonify({
            "code": 200,
            "message": f"成功处理{len(processed_files)}个PDF文件",
            "data": {
                "files": processed_files,
                "total": len(processed_files),
                "batch_id": batch_id,
                "errors": errors if errors else None
            }
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"服务器内部错误: {str(e)}",
            "data": None
        }), 500


def process_single_pdf_task(pdf_url, data_item, custom_font, custom_fontsize, pdf_index, data_index, file_handler,
                            pdf_processor, oss_uploader, customer_code, order_no):
    """
    处理单个PDF文件任务

    Args:
        pdf_url: PDF URL
        data_item: 数据项
        custom_font: 自定义字体
        custom_fontsize: 自定义字体大小
        pdf_index: PDF索引
        data_index: 数据索引

    Returns:
        dict: 处理结果
    """
    try:
        # 下载PDF文件
        local_pdf_path = file_handler.download_pdf_from_url(pdf_url)

        # 将数据转换为替换字典
        replacements = {}
        for key, value in data_item.items():
            if value is not None:
                replacements[str(key)] = str(value)

        if not replacements:
            return {
                'success': False,
                'error': '没有有效的替换数据'
            }

        # 处理PDF
        output_path = pdf_processor.process_pdf(
            local_pdf_path,
            replacements,
            custom_font,
            custom_fontsize
        )

        # 上传到OSS
        try:
            oss_url = oss_uploader.upload_to_oss(output_path, customer_code, order_no)

            # 生成文件名
            filename = f"processed_{pdf_index + 1}_{data_index + 1}_{os.path.basename(output_path)}"

            # 清理本地文件
            file_handler.cleanup_files(local_pdf_path, output_path)

            return {
                'success': True,
                'file_info': {
                    'original_url': pdf_url,
                    'processed_url': oss_url,
                    'filename': filename,
                    'pdf_index': pdf_index,
                    'data_index': data_index
                }
            }
        except Exception as e:
            # OSS上传失败，返回本地URL
            _, local_url = file_handler.save_output_pdf(output_path)

            file_handler.cleanup_files(local_pdf_path)

            return {
                'success': True,
                'file_info': {
                    'original_url': pdf_url,
                    'processed_url': local_url,
                    'filename': os.path.basename(output_path),
                    'pdf_index': pdf_index,
                    'data_index': data_index,
                    'note': '使用本地存储（OSS上传失败）'
                }
            }

    except Exception as e:
        # 清理临时文件
        if 'local_pdf_path' in locals():
            file_handler.cleanup_files(local_pdf_path)

        return {
            'success': False,
            'error': str(e)
        }


@app.route('/api/fill-pdf-batch', methods=['POST'])
def fill_pdf_batch():
    """
    批量PDF表单填充API接口（优化版本）

    请求参数（JSON格式）:
    {
        "data": [  # 数据列表，每个元素对应一个PDF
            {
                "replacements": {
                    "PO_NO": "PO20240001",
                    "NAME": "张三"
                },
                "url": "http://example.com/document1.pdf",
                "font": "Helvetica",  # 可选
                "fontsize": 12        # 可选
            },
            {
                "replacements": {
                    "PO_NO": "PO20240002",
                    "NAME": "李四"
                },
                "url": "http://example.com/document2.pdf"
            }
        ]
    }

    返回:
    {
        "code": 200,
        "message": "success",
        "data": {
            "results": [
                {
                    "original_url": "http://example.com/document1.pdf",
                    "processed_url": "https://oss.example.com/pdf/output1.pdf",
                    "success": true
                },
                {
                    "original_url": "http://example.com/document2.pdf",
                    "processed_url": "https://oss.example.com/pdf/output2.pdf",
                    "success": true
                }
            ]
        }
    }
    """
    try:
        if not request.is_json:
            return jsonify({
                "code": 400,
                "message": "请求必须是JSON格式",
                "data": None
            }), 400

        request_data = request.get_json()

        if 'data' not in request_data or not isinstance(request_data['data'], list):
            return jsonify({
                "code": 400,
                "message": "缺少或无效的data参数，应为数组",
                "data": None
            }), 400

        tasks = request_data['data']

        # 限制最大处理数量
        max_tasks = 1000
        if len(tasks) > max_tasks:
            return jsonify({
                "code": 400,
                "message": f"一次最多处理{max_tasks}个任务",
                "data": None
            }), 400

        # 处理每个任务
        results = []
        errors = []

        for i, task in enumerate(tasks):
            try:
                # 验证任务数据
                if 'url' not in task or 'replacements' not in task:
                    errors.append({
                        'index': i,
                        'error': '缺少url或replacements参数'
                    })
                    continue

                # 下载PDF
                local_pdf_path = file_handler.download_pdf_from_url(task['url'])

                # 处理PDF
                output_path = pdf_processor.process_pdf(
                    local_pdf_path,
                    task['replacements'],
                    task.get('font'),
                    task.get('fontsize')
                )

                # 上传到OSS
                try:
                    customer_code = task.get('customer_code')
                    order_no = task.get('order_no')
                    oss_url = oss_uploader.upload_to_oss(output_path, customer_code, order_no)

                    results.append({
                        'original_url': task['url'],
                        'processed_url': oss_url,
                        'filename': os.path.basename(output_path),
                        'success': True,
                        'index': i
                    })
                except Exception as e:
                    # 使用本地URL
                    _, local_url = file_handler.save_output_pdf(output_path)

                    results.append({
                        'original_url': task['url'],
                        'processed_url': local_url,
                        'filename': os.path.basename(output_path),
                        'success': True,
                        'note': '使用本地存储',
                        'index': i
                    })

                # 清理文件
                file_handler.cleanup_files(local_pdf_path, output_path)

            except Exception as e:
                errors.append({
                    'index': i,
                    'url': task.get('url', 'unknown'),
                    'error': str(e)
                })

        # 返回结果
        return jsonify({
            "code": 200,
            "message": f"处理完成，成功{len(results)}个，失败{len(errors)}个",
            "data": {
                "results": results,
                "errors": errors if errors else None,
                "statistics": {
                    "total": len(tasks),
                    "success": len(results),
                    "failed": len(errors)
                }
            }
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"服务器内部错误: {str(e)}",
            "data": None
        }), 500


@app.route('/api/upload-pdf', methods=['POST'])
def upload_pdf():
    """
    上传PDF文件API接口

    请求参数（FormData格式）:
    - file: PDF文件

    返回:
    {
        "code": 200,
        "message": "success",
        "data": {
            "url": "http://localhost:5000/static/uploads/filename.pdf"
        }
    }
    """
    try:
        # 检查是否有文件
        if 'file' not in request.files:
            return jsonify({
                "code": 400,
                "message": "没有上传文件",
                "data": None
            }), 400

        file = request.files['file']

        # 检查文件名
        if file.filename == '':
            return jsonify({
                "code": 400,
                "message": "没有选择文件",
                "data": None
            }), 400

        # 检查文件类型
        if not file_handler.is_allowed_file(file.filename):
            return jsonify({
                "code": 400,
                "message": "只允许上传PDF文件",
                "data": None
            }), 400

        # 保存文件
        filename = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.pdf"
        filepath = os.path.join(Config.UPLOAD_FOLDER, filename)

        file.save(filepath)

        # 验证PDF文件
        try:
            doc = fitz.open(filepath)
            doc.close()
        except Exception:
            os.remove(filepath)
            return jsonify({
                "code": 400,
                "message": "上传的文件不是有效的PDF格式",
                "data": None
            }), 400

        # 生成访问URL
        base_url = os.environ.get('BASE_URL', 'http://localhost:5000')
        access_url = f"{base_url}/static/uploads/{filename}"

        return jsonify({
            "code": 200,
            "message": "文件上传成功",
            "data": {
                "url": access_url,
                "filename": filename,
                "local_path": filepath
            }
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"文件上传失败: {str(e)}",
            "data": None
        }), 500


@app.route('/api/detect-fields', methods=['POST'])
def detect_fields():
    """
    检测PDF表单字段

    请求参数:
    {
        "url": "http://example.com/document.pdf"
    }

    返回:
    {
        "code": 200,
        "message": "success",
        "data": {
            "fields": ["PO_NO", "CUSTOMER_NAME", "DATE", "AMOUNT"],
            "sample_texts": {
                "PO_NO": "PO20240001",
                "CUSTOMER_NAME": "示例公司"
            }
        }
    }
    """
    try:
        if not request.is_json:
            return jsonify({
                "code": 400,
                "message": "请求必须是JSON格式",
                "data": None
            }), 400

        request_data = request.get_json()

        if 'url' not in request_data:
            return jsonify({
                "code": 400,
                "message": "缺少必需参数: url",
                "data": None
            }), 400

        pdf_url = request_data['url']

        # 下载PDF文件
        try:
            local_pdf_path = file_handler.download_pdf_from_url(pdf_url)
        except Exception as e:
            return jsonify({
                "code": 500,
                "message": f"下载PDF失败: {str(e)}",
                "data": None
            }), 500

        try:
            # 检测字段
            fields_info = pdf_processor.detect_form_fields(local_pdf_path)

            # 生成Excel模板
            excel_url = generate_excel_template(fields_info["fields"])
            fields_info["excel_template_url"] = excel_url

            # 清理临时文件
            file_handler.cleanup_files(local_pdf_path)

            return jsonify({
                "code": 200,
                "message": "字段检测成功",
                "data": fields_info
            }), 200

        except Exception as e:
            file_handler.cleanup_files(local_pdf_path)
            return jsonify({
                "code": 500,
                "message": f"检测字段失败: {str(e)}",
                "data": None
            }), 500

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"服务器内部错误: {str(e)}",
            "data": None
        }), 500


def generate_excel_template(fields):
    """
    生成Excel模板文件

    Args:
        fields: 字段列表

    Returns:
        str: Excel文件的访问URL
    """
    if not fields:
        fields = ["字段1", "字段2", "字段3"]  # 默认字段

    # 创建DataFrame，第一行为表头，第二行为示例数据
    fields.insert(0,'pdf_name')
    df = pd.DataFrame(columns=fields)

    # 添加几行示例数据
    example_row = {}
    for field in fields:
        if "pdf_name" in field.lower():
            example_row[field] = "文件名"
        else:
            example_row[field] = f"示例{field}"

    df.loc[0] = example_row

    # 生成文件名
    fields_str = "_".join(fields[:3])  # 只取前5个字段作为文件名的一部分，避免过长
    if len(fields) > 3:
        fields_str += f"_et_al"  # 如果超过5个字段，添加后缀
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"模板_{fields_str}_{timestamp}.xlsx"

    # 确保模板目录存在
    template_dir = os.path.join(Config.BASE_DIR, 'static', 'templates')
    os.makedirs(template_dir, exist_ok=True)

    # 保存Excel文件
    filepath = os.path.join(template_dir, filename)
    df.to_excel(filepath, index=False)

    # 生成访问URL
    base_url = os.environ.get('BASE_URL', 'http://localhost:5000')
    access_url = f"{base_url}/static/templates/{filename}"

    return access_url

@app.route('/api/get-fonts', methods=['POST'])
def get_fonts():
    """
    获取PDF中使用的字体

    请求参数:
    {
        "url": "http://example.com/document.pdf"
    }

    返回:
    {
        "code": 200,
        "message": "success",
        "data": {
            "fonts": ["Helvetica", "Times-Roman", "Arial"],
            "font_count": 3
        }
    }
    """
    try:
        if not request.is_json:
            return jsonify({
                "code": 400,
                "message": "请求必须是JSON格式",
                "data": None
            }), 400

        request_data = request.get_json()

        if 'url' not in request_data:
            return jsonify({
                "code": 400,
                "message": "缺少必需参数: url",
                "data": None
            }), 400

        pdf_url = request_data['url']

        # 下载PDF文件
        try:
            local_pdf_path = file_handler.download_pdf_from_url(pdf_url)
        except Exception as e:
            return jsonify({
                "code": 500,
                "message": f"下载PDF失败: {str(e)}",
                "data": None
            }), 500

        try:
            # 获取字体
            fonts = pdf_processor.get_pdf_fonts(local_pdf_path)

            # 清理临时文件
            file_handler.cleanup_files(local_pdf_path)

            return jsonify({
                "code": 200,
                "message": "获取字体成功",
                "data": {
                    "fonts": fonts,
                    "font_count": len(fonts)
                }
            }), 200

        except Exception as e:
            file_handler.cleanup_files(local_pdf_path)
            return jsonify({
                "code": 500,
                "message": f"获取字体失败: {str(e)}",
                "data": None
            }), 500

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"服务器内部错误: {str(e)}",
            "data": None
        }), 500


@app.errorhandler(404)
def not_found(error):
    """404错误处理"""
    return jsonify({
        "code": 404,
        "message": "请求的资源不存在",
        "data": None
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """500错误处理"""
    return jsonify({
        "code": 500,
        "message": "服务器内部错误",
        "data": None
    }), 500


if __name__ == '__main__':
    # 创建必要的目录
    for folder in [Config.UPLOAD_FOLDER, Config.OUTPUT_FOLDER]:
        os.makedirs(folder, exist_ok=True)

    # 启动Flask应用
    app.run(host='0.0.0.0', port=5000, debug=True)