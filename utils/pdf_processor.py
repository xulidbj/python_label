import os
import fitz
import pdfplumber
import re
from typing import Dict, Optional, Tuple, List, Any
from config import Config


class PDFProcessor:
    def __init__(self, custom_font_mapping: Optional[Dict] = None):
        """
        初始化PDF处理器
        """
        self.font_mapping = Config.DEFAULT_FONT_MAPPING.copy()
        if custom_font_mapping:
            self.font_mapping.update(custom_font_mapping)

    def process_pdf(self, pdf_path: str, replacements: Dict[str, str],
                    custom_font: Optional[str] = None,
                    custom_fontsize: Optional[float] = None) -> str:
        """
        处理PDF文件，替换文本内容
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

        if not replacements:
            raise ValueError("替换内容不能为空")

        # 生成输出文件路径
        output_filename = Config.get_output_filename()
        output_pdf = os.path.join(Config.OUTPUT_FOLDER, output_filename)

        # 使用改进的文本替换方法
        output_path = self._improved_text_replacement(
            pdf_path, replacements, custom_font, custom_fontsize, output_pdf
        )

        return output_path

    def _improved_text_replacement(self, input_pdf: str, replacements: Dict[str, str],
                                   custom_font: Optional[str],
                                   custom_fontsize: Optional[float],
                                   output_pdf: str) -> str:
        """
        改进的文本替换方法
        """
        doc = fitz.open(input_pdf)

        # 首先检查是否是表单PDF
        if doc.is_form_pdf:
            print("检测到PDF包含表单字段，使用表单填充方式...")
            self._fill_pdf_form_simple(doc, replacements)
        else:
            print("普通PDF，使用改进的文本替换方式...")
            self._replace_text_simple(doc, replacements, custom_font, custom_fontsize)

        # 保存文档
        doc.save(output_pdf)
        doc.close()

        print(f"PDF处理完成，保存到: {output_pdf}")
        return output_pdf

    def _fill_pdf_form_simple(self, doc, replacements: Dict[str, str]):
        """
        简单表单填充
        """
        try:
            form = doc.load_form()
            filled_count = 0

            for field_name, field_value in replacements.items():
                try:
                    # 尝试直接设置字段值
                    form[field_name] = str(field_value)
                    filled_count += 1
                    print(f"✓ 填充表单字段 '{field_name}' = '{field_value}'")
                except:
                    print(f"✗ 字段 '{field_name}' 不存在或无法填充")

            if filled_count > 0:
                form.update()
                print(f"成功填充 {filled_count} 个表单字段")

        except Exception as e:
            print(f"表单处理失败: {e}")
            # 回退到文本替换
            self._replace_text_simple(doc, replacements)

    def _replace_text_simple(self, doc, replacements: Dict[str, str],
                             custom_font: Optional[str] = None,
                             custom_fontsize: Optional[float] = None):
        """
        简单直接的文本替换
        """
        for page_num in range(len(doc)):
            page = doc[page_num]

            # 获取页面中的所有文本和位置
            text_blocks = self._get_page_text_with_positions(page)

            for old_text, new_text in replacements.items():
                # 查找文本位置
                text_positions = self._find_text_positions(text_blocks, old_text)

                if text_positions:
                    print(f"在第{page_num + 1}页找到 '{old_text}'，替换为 '{new_text}'")

                    for pos_info in text_positions:
                        self._replace_single_text(
                            page, pos_info, new_text, custom_font, custom_fontsize
                        )

    def _get_page_text_with_positions(self, page):
        """
        获取页面中的所有文本及其位置和样式
        """
        text_blocks = []

        try:
            # 使用PyMuPDF获取文本字典
            text_dict = page.get_text("dict")

            for block in text_dict.get("blocks", []):
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span.get("text", "")
                            bbox = span.get("bbox", [0, 0, 0, 0])
                            font = span.get("font", "helv")
                            size = span.get("size", 11)

                            # 处理颜色
                            color = span.get("color", (0, 0, 0))
                            if isinstance(color, (int, float)):
                                # 如果是单个值，转换为RGB
                                if 0 <= color <= 1:
                                    color = (color, color, color)
                                else:
                                    color = (color / 255.0, color / 255.0, color / 255.0)
                            elif isinstance(color, (list, tuple)):
                                if len(color) == 3:
                                    # 检查是否需要归一化
                                    if any(c > 1 for c in color):
                                        color = tuple(c / 255.0 for c in color)
                                    else:
                                        color = tuple(color)
                                else:
                                    color = (0, 0, 0)
                            else:
                                color = (0, 0, 0)

                            text_blocks.append({
                                "text": text,
                                "bbox": bbox,
                                "font": font,
                                "size": size,
                                "color": color,
                                "rect": fitz.Rect(bbox)
                            })

        except Exception as e:
            print(f"获取页面文本失败: {e}")

        return text_blocks

    def _find_text_positions(self, text_blocks, search_text):
        """
        查找文本位置
        """
        positions = []

        for block in text_blocks:
            if search_text in block["text"]:
                positions.append(block)

        return positions

    def _replace_single_text(self, page, pos_info, new_text: str,
                             custom_font: Optional[str] = None,
                             custom_fontsize: Optional[float] = None):
        """
        替换单个文本
        """
        try:
            rect = pos_info["rect"]
            original_font = pos_info["font"]
            original_size = pos_info["size"]
            original_color = pos_info["color"]

            print(f"原字体: {original_font}, 大小: {original_size}, 颜色: {original_color}")

            # 1. 清除原文本区域
            # 稍微扩大清除范围以确保完全清除
            expand_amount = original_size * 0.2
            clear_rect = rect + (-expand_amount, -expand_amount, expand_amount, expand_amount)

            # 使用白色填充清除
            page.draw_rect(clear_rect, color=(1, 1, 1), fill=(1, 1, 1))

            # 2. 确定要使用的字体和大小
            font_to_use = custom_font if custom_font else original_font
            fontsize_to_use = custom_fontsize if custom_fontsize else original_size

            # 3. 计算文本位置（居中）
            # 估算新文本的宽度
            estimated_width = len(new_text) * fontsize_to_use * 0.6

            if estimated_width < rect.width:
                # 文本较短，居中
                x_pos = rect.x0 + (rect.width - estimated_width) / 2
            else:
                # 文本较长，左对齐
                x_pos = rect.x0

            # 垂直居中
            y_pos = rect.y0 + rect.height / 2 + fontsize_to_use * 0.35

            # 4. 尝试插入文本
            success = False
            error_message = ""

            # 方法1: 使用原字体
            try:
                page.insert_text(
                    (x_pos, y_pos),
                    new_text,
                    fontname=original_font,
                    fontsize=fontsize_to_use,
                    color=original_color
                )
                success = True
                print(f"✓ 使用原字体插入成功: {original_font}")
            except Exception as e1:
                error_message = str(e1)
                print(f"✗ 原字体失败: {e1}")

            # 方法2: 如果指定了自定义字体，尝试使用
            if not success and custom_font:
                try:
                    page.insert_text(
                        (x_pos, y_pos),
                        new_text,
                        fontname=custom_font,
                        fontsize=fontsize_to_use,
                        color=original_color
                    )
                    success = True
                    print(f"✓ 使用自定义字体插入成功: {custom_font}")
                except Exception as e2:
                    print(f"✗ 自定义字体失败: {e2}")

            # 方法3: 尝试使用字体映射
            if not success:
                mapped_font = self.font_mapping.get(original_font)
                if mapped_font:
                    try:
                        page.insert_text(
                            (x_pos, y_pos),
                            new_text,
                            fontname=mapped_font,
                            fontsize=fontsize_to_use,
                            color=original_color
                        )
                        success = True
                        print(f"✓ 使用映射字体插入成功: {mapped_font}")
                    except Exception as e3:
                        print(f"✗ 映射字体失败: {e3}")

            # 方法4: 不指定字体（使用默认）
            if not success:
                try:
                    page.insert_text(
                        (x_pos, y_pos),
                        new_text,
                        fontsize=fontsize_to_use,
                        color=original_color
                    )
                    success = True
                    print("✓ 使用默认字体插入成功")
                except Exception as e4:
                    print(f"✗ 默认字体失败: {e4}")

            # 方法5: 最小化参数
            if not success:
                try:
                    page.insert_text(
                        (x_pos, y_pos),
                        new_text,
                        fontsize=fontsize_to_use
                    )
                    success = True
                    print("✓ 最小参数插入成功")
                except Exception as e5:
                    print(f"✗ 所有方法都失败: {e5}")
                    # 最后尝试：在位置添加注释
                    page.add_text_annot(rect.tl, f"[替换为: {new_text}]")

        except Exception as e:
            print(f"替换文本时发生错误: {e}")

    def _contains_chinese(self, text: str) -> bool:
        """
        检查字符串是否包含中文字符
        """
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                return True
        return False

    def get_pdf_fonts_info(self, pdf_path: str) -> Dict:
        """
        获取PDF中使用的所有字体详细信息
        """
        font_info = {}
        doc = fitz.open(pdf_path)

        for page_num in range(len(doc)):
            page = doc[page_num]

            try:
                text_dict = page.get_text("dict")

                for block in text_dict.get("blocks", []):
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                fontname = span.get("font", "Unknown")
                                fontsize = span.get("size", 0)
                                text = span.get("text", "")[:50]

                                if fontname not in font_info:
                                    font_info[fontname] = {
                                        "pages": set(),
                                        "sizes": set(),
                                        "sample_texts": [],
                                        "count": 0
                                    }

                                font_info[fontname]["pages"].add(page_num + 1)
                                font_info[fontname]["sizes"].add(fontsize)
                                if text:
                                    font_info[fontname]["sample_texts"].append(text)
                                font_info[fontname]["count"] += 1

            except Exception as e:
                print(f"第{page_num + 1}页分析失败: {e}")

        doc.close()

        # 格式化输出
        formatted_info = {}
        for fontname, info in font_info.items():
            formatted_info[fontname] = {
                "used_on_pages": sorted(list(info["pages"])),
                "font_sizes": sorted(list(info["sizes"])),
                "sample_texts": info["sample_texts"][:3],
                "usage_count": info["count"]
            }

        return formatted_info

    def get_form_fields(self, pdf_path: str) -> Dict[str, Any]:
        """
        获取PDF表单字段信息
        """
        doc = fitz.open(pdf_path)
        form_fields = {}

        if doc.is_form_pdf:
            try:
                # 尝试加载表单
                form = doc.load_form()

                # 遍历所有widgets
                for widget in doc.widgets():
                    field_name = widget.field_name
                    if field_name:
                        form_fields[field_name] = {
                            "type": widget.field_type,
                            "value": widget.field_value,
                            "rect": {
                                "x0": widget.rect.x0,
                                "y0": widget.rect.y0,
                                "x1": widget.rect.x1,
                                "y1": widget.rect.y1
                            }
                        }

            except Exception as e:
                print(f"获取表单字段失败: {e}")

        doc.close()
        return form_fields


# 使用示例和测试
if __name__ == "__main__":
    # 测试函数
    def test_pdf_processor():
        processor = PDFProcessor()

        # 测试文件
        pdf_path = "test.pdf"

        if not os.path.exists(pdf_path):
            print(f"测试文件不存在: {pdf_path}")
            return

        print("=== PDF字体分析 ===")
        font_info = processor.get_pdf_fonts_info(pdf_path)
        for fontname, info in font_info.items():
            print(f"\n字体: {fontname}")
            print(f"  使用页面: {info['used_on_pages']}")
            print(f"  字体大小: {info['font_sizes']}")
            print(f"  样本文本: {info['sample_texts']}")

        print("\n=== 执行文本替换 ===")
        replacements = {
            "PO_NO": "PO20240001",
            "CUSTOMER_NAME": "zhangsan",
            "AMOUNT": "10000.00",
            "DESCRIPTION": "caigou"
        }

        try:
            output_path = processor.process_pdf(pdf_path, replacements)
            print(f"✓ 处理成功，输出文件: {output_path}")
        except Exception as e:
            print(f"✗ 处理失败: {e}")

            # 尝试简单方法
            print("\n=== 尝试简单方法 ===")
            try:
                doc = fitz.open(pdf_path)

                for page in doc:
                    for old_text, new_text in replacements.items():
                        text_instances = page.search_for(old_text)
                        if text_instances:
                            print(f"找到 '{old_text}'，替换为 '{new_text}'")

                            for rect in text_instances:
                                # 简单清除和插入
                                page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))
                                page.insert_text(rect.tl, new_text, fontsize=11)

                output_path = "output_simple.pdf"
                doc.save(output_path)
                doc.close()
                print(f"✓ 简单方法成功，输出文件: {output_path}")

            except Exception as e2:
                print(f"✗ 简单方法也失败: {e2}")


    # 运行测试
    test_pdf_processor()