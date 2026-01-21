import os
import fitz
import re
import logging
import tempfile
from typing import Dict, Optional, List, Any, Tuple, Set
from dataclasses import dataclass
from config import Config
from collections import defaultdict

# 配置日志
logger = logging.getLogger(__name__)


@dataclass
class TextSpan:
    """文本块信息"""
    text: str
    bbox: Tuple[float, float, float, float]
    font: str
    size: float
    color: Tuple[float, float, float]
    page_num: int = 0


class PDFProcessor:
    def __init__(self, custom_font_mapping: Optional[Dict] = None):
        """
        初始化PDF处理器
        """
        self.font_mapping = Config.DEFAULT_FONT_MAPPING.copy()
        if custom_font_mapping:
            self.font_mapping.update(custom_font_mapping)

        # 常见字体缓存
        self.available_fonts = self._get_available_fonts()

        # API 版本检测
        self._detect_api_version()

    def _detect_api_version(self):
        """检测 PyMuPDF API 版本"""
        try:
            # 尝试获取版本信息
            import pymupdf
            version = getattr(pymupdf, '__version__', 'unknown')
            logger.info(f"PyMuPDF 版本: {version}")

            # 检查 widgets 方法是否存在
            doc = fitz.open()
            has_widgets = hasattr(doc, 'widgets')
            has_get_widgets = False
            if has_widgets:
                try:
                    # 尝试调用 widgets() 方法
                    widgets = list(doc.widgets())
                    has_get_widgets = True
                except:
                    pass

            logger.info(f"API 检测: widgets={has_widgets}, get_widgets={has_get_widgets}")
            doc.close()

            # 设置 API 标志
            self.use_new_widget_api = has_get_widgets

        except Exception as e:
            logger.warning(f"API 版本检测失败: {e}")
            self.use_new_widget_api = False

    def _get_available_fonts(self) -> Set[str]:
        """获取系统可用字体列表"""
        try:
            # PyMuPDF 内置字体
            builtin_fonts = {
                "helv", "hebo", "cour", "tiro", "symb", "zadb",
                "helvetica", "helvetica-bold", "helvetica-oblique", "helvetica-boldoblique",
                "times-roman", "times-bold", "times-italic", "times-bolditalic",
                "courier", "courier-bold", "courier-oblique", "courier-boldoblique"
            }

            # 尝试获取更多字体
            doc = fitz.open()
            page = doc.new_page()

            # 测试常见字体是否可用
            test_fonts = {
                "simsun", "simhei", "microsoftyahei",
                "fangsong", "kaiti", "songti", "heiti"
            }
            available = set(builtin_fonts)

            for font in test_fonts:
                try:
                    # 尝试不同字体名称变体
                    variants = [font, font.lower(), font.upper(), font.capitalize()]
                    for variant in variants:
                        try:
                            page.insert_text((10, 10), "测", fontname=variant, fontsize=10)
                            available.add(variant)
                            logger.debug(f"字体可用: {variant}")
                            break
                        except:
                            continue
                except:
                    pass

            doc.close()
            return available

        except Exception as e:
            logger.warning(f"获取可用字体失败: {e}")
            return {"helv", "helvetica", "times-roman", "courier"}

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

        logger.info(f"开始处理PDF: {pdf_path}")
        logger.info(f"替换内容: {replacements}")

        pdf_name = replacements.get('pdf_name','')

        # 生成输出文件路径
        output_filename = Config.get_output_filename(pdf_name)
        output_pdf = os.path.join(Config.OUTPUT_FOLDER, output_filename)

        # 使用改进的文本替换方法
        output_path = self._improved_text_replacement(
            pdf_path, replacements, custom_font, custom_fontsize, output_pdf
        )

        logger.info(f"PDF处理完成: {output_path}")
        return output_path

    def _improved_text_replacement(self, input_pdf: str, replacements: Dict[str, str],
                                   custom_font: Optional[str],
                                   custom_fontsize: Optional[float],
                                   output_pdf: str) -> str:
        """
        改进的文本替换方法
        """
        doc = fitz.open(input_pdf)

        try:
            # 首先尝试表单填充
            try:
                if self._has_form_fields(doc):
                    logger.info("检测到PDF包含表单字段，使用表单填充方式...")
                    self._fill_pdf_form_fields(doc, replacements)
                else:
                    logger.info("普通PDF，使用文本替换方式...")
                    self._replace_text_advanced(doc, replacements, custom_font, custom_fontsize)
            except Exception as e:
                logger.warning(f"表单填充失败，回退到文本替换: {e}")
                self._replace_text_advanced(doc, replacements, custom_font, custom_fontsize)

            # 保存文档
            doc.save(output_pdf)
            logger.info(f"PDF处理完成，保存到: {output_pdf}")

        finally:
            doc.close()

        return output_pdf

    def _has_form_fields(self, doc) -> bool:
        """检查PDF是否包含表单字段（兼容版本）"""
        try:
            # 方法1：检查是否为表单PDF
            if hasattr(doc, 'is_form_pdf') and doc.is_form_pdf:
                return True

            # 方法2：遍历所有页面检查
            for page_num in range(len(doc)):
                page = doc[page_num]

                # 尝试不同方法获取字段
                if hasattr(page, 'widgets'):
                    try:
                        widgets = list(page.widgets())
                        if widgets:
                            return True
                    except:
                        pass

                # 检查 annots
                if hasattr(page, 'annots'):
                    try:
                        annots = page.annots()
                        if annots:
                            for annot in annots:
                                if annot.type[0] == 15:  # 15 是 Widget 注释类型
                                    return True
                    except:
                        pass

            return False

        except Exception as e:
            logger.warning(f"检查表单字段失败: {e}")
            return False

    def _fill_pdf_form_fields(self, doc, replacements: Dict[str, str]):
        """
        填充PDF表单字段（兼容版本）
        """
        filled_count = 0

        try:
            # 收集所有字段
            form_fields = {}

            for page_num in range(len(doc)):
                page = doc[page_num]

                # 尝试不同方法获取字段
                widgets = []

                # 方法1：使用 page.widgets()
                if hasattr(page, 'widgets'):
                    try:
                        widgets = list(page.widgets())
                    except Exception as e:
                        logger.debug(f"page.widgets() 失败: {e}")

                # 方法2：使用 page.get_widgets()
                if not widgets and hasattr(page, 'get_widgets'):
                    try:
                        widgets = page.get_widgets()
                    except Exception as e:
                        logger.debug(f"page.get_widgets() 失败: {e}")

                # 方法3：遍历 annots
                if not widgets and hasattr(page, 'annots'):
                    try:
                        annots = page.annots()
                        if annots:
                            for annot in annots:
                                # 检查是否为 widget 注释
                                if hasattr(annot, 'widget') and annot.widget:
                                    widgets.append(annot.widget)
                    except Exception as e:
                        logger.debug(f"遍历 annots 失败: {e}")

                # 处理找到的 widgets
                for widget in widgets:
                    try:
                        field_name = None

                        # 尝试不同属性名获取字段名
                        for attr_name in ['field_name', 'fieldName', 'name']:
                            if hasattr(widget, attr_name):
                                field_name = getattr(widget, attr_name)
                                if field_name:
                                    break

                        if field_name:
                            form_fields[field_name] = widget
                    except Exception as e:
                        logger.debug(f"获取widget信息失败: {e}")

            logger.info(f"找到 {len(form_fields)} 个表单字段")

            if not form_fields:
                raise Exception("未找到表单字段")

            # 填充字段
            for field_name, field_value in replacements.items():
                if field_name in form_fields:
                    widget = form_fields[field_name]

                    try:
                        # 尝试不同方法设置字段值
                        success = False

                        # 方法1：直接设置 field_value 属性
                        if hasattr(widget, 'field_value'):
                            widget.field_value = str(field_value)
                            success = True

                        # 方法2：调用 set_field_value 方法
                        elif hasattr(widget, 'set_field_value'):
                            widget.set_field_value(str(field_value))
                            success = True

                        # 方法3：使用 update 方法
                        if success and hasattr(widget, 'update'):
                            widget.update()
                            filled_count += 1
                            logger.info(f"✓ 填充表单字段 '{field_name}' = '{field_value}'")
                        else:
                            logger.warning(f"✗ 字段 '{field_name}' 不支持设置值")

                    except Exception as e:
                        logger.warning(f"✗ 字段 '{field_name}' 填充失败: {e}")
                else:
                    # 尝试模糊匹配
                    matched = False
                    for existing_field in form_fields.keys():
                        if (field_name.lower() in existing_field.lower() or
                                existing_field.lower() in field_name.lower()):

                            widget = form_fields[existing_field]
                            try:
                                if hasattr(widget, 'field_value'):
                                    widget.field_value = str(field_value)
                                    if hasattr(widget, 'update'):
                                        widget.update()
                                        filled_count += 1
                                        logger.info(f"✓ 模糊匹配填充 '{existing_field}' = '{field_value}'")
                                        matched = True
                            except Exception as e:
                                logger.warning(f"✗ 模糊匹配字段 '{existing_field}' 填充失败: {e}")

                    if not matched:
                        logger.warning(f"✗ 未找到字段 '{field_name}'")

            if filled_count > 0:
                logger.info(f"成功填充 {filled_count} 个表单字段")
            else:
                logger.warning("未填充任何字段")
                raise Exception("表单填充失败")

        except Exception as e:
            logger.error(f"表单处理失败: {e}")
            raise

    def _replace_text_advanced(self, doc, replacements: Dict[str, str],
                               custom_font: Optional[str] = None,
                               custom_fontsize: Optional[float] = None):
        """
        高级文本替换方法
        """
        total_replacements = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_replacements = 0

            # 获取页面中的所有文本块
            text_spans = self._extract_text_spans(page, page_num)

            for old_text, new_text in replacements.items():
                if not old_text or not new_text:
                    continue

                # 查找文本位置（支持部分匹配）
                matching_spans = self._find_matching_spans(text_spans, old_text)

                if matching_spans:
                    logger.debug(f"在第{page_num + 1}页找到 '{old_text}'，替换为 '{new_text}'")

                    for span in matching_spans:
                        try:
                            success = self._replace_text_in_span(
                                page, span, new_text, custom_font, custom_fontsize
                            )
                            if success:
                                page_replacements += 1
                        except Exception as e:
                            logger.warning(f"替换文本失败: {e}")

            if page_replacements > 0:
                logger.info(f"第{page_num + 1}页完成 {page_replacements} 处替换")
                total_replacements += page_replacements

        logger.info(f"总共完成 {total_replacements} 处文本替换")

        if total_replacements == 0:
            logger.warning("未找到任何匹配的文本，尝试使用简单搜索替换")
            self._replace_text_simple_fallback(doc, replacements, custom_font, custom_fontsize)

    def _replace_text_simple_fallback(self, doc, replacements: Dict[str, str],
                                      custom_font: Optional[str] = None,
                                      custom_fontsize: Optional[float] = None):
        """
        简单回退文本替换方法
        """
        logger.info("使用简单回退方法进行文本替换")

        for page_num in range(len(doc)):
            page = doc[page_num]

            for old_text, new_text in replacements.items():
                if not old_text:
                    continue

                try:
                    # 使用 search_for 查找文本
                    text_instances = page.search_for(old_text)

                    if text_instances:
                        logger.info(f"在第{page_num + 1}页找到 '{old_text}'，替换为 '{new_text}'")

                        for rect in text_instances:
                            try:
                                # 清除原文本
                                page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

                                # 插入新文本
                                fontsize = custom_fontsize if custom_fontsize else 11
                                fontname = custom_font if custom_font else "helv"

                                # 尝试不同方法插入文本
                                try:
                                    page.insert_text(
                                        rect.tl,
                                        new_text,
                                        fontname=fontname,
                                        fontsize=fontsize
                                    )
                                except:
                                    # 如果失败，尝试不使用字体名
                                    page.insert_text(
                                        rect.tl,
                                        new_text,
                                        fontsize=fontsize
                                    )

                            except Exception as e:
                                logger.warning(f"简单替换失败: {e}")

                except Exception as e:
                    logger.warning(f"搜索文本失败: {e}")

    def _extract_text_spans(self, page, page_num: int = 0) -> List[TextSpan]:
        """
        提取页面中的文本块
        """
        text_spans = []

        try:
            # 方法1：使用 get_text("dict") - 推荐方法
            try:
                text_dict = page.get_text("dict")

                for block in text_dict.get("blocks", []):
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                text = span.get("text", "").strip()
                                if not text:
                                    continue

                                bbox = span.get("bbox", [0, 0, 0, 0])
                                font = span.get("font", "helv").lower()
                                size = span.get("size", 11)
                                color = self._normalize_color(span.get("color", (0, 0, 0)))

                                text_spans.append(TextSpan(
                                    text=text,
                                    bbox=tuple(bbox),
                                    font=font,
                                    size=size,
                                    color=color,
                                    page_num=page_num
                                ))
            except Exception as e:
                logger.debug(f"get_text('dict') 失败: {e}")

                # 方法2：使用 get_text("words")
                try:
                    words = page.get_text("words")
                    for word in words:
                        text = word[4].strip()
                        if text:
                            bbox = (word[0], word[1], word[2], word[3])
                            text_spans.append(TextSpan(
                                text=text,
                                bbox=bbox,
                                font="helv",
                                size=11,
                                color=(0, 0, 0),
                                page_num=page_num
                            ))
                except Exception as e2:
                    logger.debug(f"get_text('words') 失败: {e2}")

            logger.debug(f"提取到 {len(text_spans)} 个文本块")
            return text_spans

        except Exception as e:
            logger.error(f"提取文本块失败: {e}")
            return []

    def _normalize_color(self, color) -> Tuple[float, float, float]:
        """标准化颜色值"""
        try:
            if isinstance(color, (int, float)):
                # 灰度值
                if 0 <= color <= 1:
                    return (color, color, color)
                else:
                    normalized = color / 255.0
                    return (normalized, normalized, normalized)
            elif isinstance(color, (list, tuple)):
                if len(color) >= 3:
                    # 检查是否需要归一化
                    if any(isinstance(c, (int, float)) and c > 1 for c in color[:3]):
                        return tuple(c / 255.0 for c in color[:3])
                    else:
                        return tuple(color[:3])

            return (0, 0, 0)  # 默认黑色
        except Exception as e:
            logger.warning(f"颜色标准化失败: {e}")
            return (0, 0, 0)

    def _find_matching_spans(self, text_spans: List[TextSpan], search_text: str) -> List[TextSpan]:
        """
        查找匹配的文本块
        """
        matches = []

        if not search_text:
            return matches

        search_lower = search_text.lower().strip()

        for span in text_spans:
            span_text_lower = span.text.lower()

            # 1. 完全匹配
            if search_lower == span_text_lower:
                matches.append(span)
                continue

            # 2. 包含匹配
            if search_lower in span_text_lower:
                matches.append(span)
                continue

            # 3. 部分匹配（对于较长的搜索文本）
            if len(search_lower) > 3:
                # 尝试分割文本
                search_parts = re.split(r'[_\s\-\.:,;]+', search_lower)
                span_parts = re.split(r'[_\s\-\.:,;]+', span_text_lower)

                # 检查是否有足够多的共同部分
                common_parts = set(search_parts) & set(span_parts)
                if common_parts and len(common_parts) >= min(2, len(search_parts)):
                    matches.append(span)

        return matches

    def _replace_text_in_span(self, page, span: TextSpan, new_text: str,
                              custom_font: Optional[str] = None,
                              custom_fontsize: Optional[float] = None) -> bool:
        """
        在文本块中替换文本
        """
        try:
            # 创建矩形
            rect = fitz.Rect(*span.bbox)

            # 1. 清除原文本区域
            expand_x = max(span.size * 0.1, 1)
            expand_y = max(span.size * 0.05, 1)
            clear_rect = rect + (-expand_x, -expand_y, expand_x, expand_y)

            # 使用白色填充清除
            page.draw_rect(clear_rect, color=(1, 1, 1), fill=(1, 1, 1))

            # 2. 确定字体和大小
            font_to_use = self._select_font(span.font, new_text, custom_font)
            fontsize_to_use = custom_fontsize if custom_fontsize else span.size

            # 3. 计算文本位置
            # 估算文本宽度
            char_width_estimate = fontsize_to_use * 0.55
            text_width_estimate = len(new_text) * char_width_estimate

            if text_width_estimate < rect.width * 0.9:
                # 居中
                x_pos = rect.x0 + (rect.width - text_width_estimate) / 2
            else:
                # 左对齐
                x_pos = rect.x0

            # 垂直居中
            y_pos = rect.y0 + rect.height / 2 + fontsize_to_use * 0.35

            # 4. 插入文本
            insertion_point = (x_pos, y_pos)

            # 尝试多种字体
            font_candidates = []

            # 首选字体
            if font_to_use:
                font_candidates.append(font_to_use)

            # 回退字体
            font_candidates.extend(["helv", "helvetica", "times-roman", "courier"])

            # 尝试插入
            for font_candidate in font_candidates:
                try:
                    page.insert_text(
                        insertion_point,
                        new_text,
                        fontname=font_candidate,
                        fontsize=fontsize_to_use,
                        color=span.color
                    )
                    logger.debug(f"使用字体 '{font_candidate}' 插入成功")
                    return True
                except Exception as e:
                    logger.debug(f"字体 '{font_candidate}' 插入失败: {e}")

            # 所有字体都失败，尝试不使用字体名
            try:
                page.insert_text(
                    insertion_point,
                    new_text,
                    fontsize=fontsize_to_use,
                    color=span.color
                )
                logger.debug("使用默认字体插入成功")
                return True
            except Exception as e:
                logger.warning(f"所有插入方法失败: {e}")

                # 最后尝试：在位置添加注释
                try:
                    page.add_text_annot(rect.tl, f"[{new_text}]")
                    return True
                except:
                    return False

        except Exception as e:
            logger.error(f"替换文本时发生错误: {e}")
            return False

    def _select_font(self, original_font: str, text: str, custom_font: Optional[str] = None) -> str:
        """
        选择最合适的字体
        """
        # 1. 优先使用自定义字体
        if custom_font:
            return custom_font

        # 2. 检查是否需要中文字体
        if self._contains_chinese(text):
            # 中文字体映射
            chinese_font_map = {
                "simsun": "simsun",
                "simhei": "simhei",
                "microsoftyahei": "microsoftyahei",
                "songti": "simsun",
                "heiti": "simhei",
                "宋体": "simsun",
                "黑体": "simhei",
            }

            # 检查原字体是否已经是中文字体
            original_lower = original_font.lower()
            for chinese_font_key in chinese_font_map:
                if chinese_font_key in original_lower:
                    return original_font

            # 返回默认中文字体
            for font_candidate in ["simsun", "simhei", "microsoftyahei"]:
                if font_candidate in self.available_fonts:
                    return font_candidate

        # 3. 使用字体映射
        mapped_font = self.font_mapping.get(original_font)
        if mapped_font:
            return mapped_font

        # 4. 检查字体是否可用
        if original_font in self.available_fonts:
            return original_font

        # 5. 返回默认字体
        return "helv"

    def _contains_chinese(self, text: str) -> bool:
        """检查字符串是否包含中文字符"""
        return any('\u4e00' <= char <= '\u9fff' for char in text)

    # ====================== 公共API方法 ======================

    def detect_form_fields(self, pdf_path: str) -> Dict[str, Any]:
        """
        检测PDF表单字段，并提取示例文本
        """
        doc = fitz.open(pdf_path)
        fields_info = {"fields": [], "sample_texts": {}, "has_form": False}

        try:
            # 检查是否为表单PDF
            if hasattr(doc, 'is_form_pdf') and doc.is_form_pdf:
                fields_info["has_form"] = True

            # 收集字段和示例值
            field_values = {}

            for page_num in range(len(doc)):
                page = doc[page_num]

                # 尝试获取 widgets
                widgets = []

                if hasattr(page, 'widgets'):
                    try:
                        widgets = list(page.widgets())
                    except:
                        pass

                if not widgets and hasattr(page, 'get_widgets'):
                    try:
                        widgets = page.get_widgets()
                    except:
                        pass

                for widget in widgets:
                    try:
                        field_name = None

                        for attr_name in ['field_name', 'fieldName', 'name']:
                            if hasattr(widget, attr_name):
                                field_name = getattr(widget, attr_name)
                                if field_name:
                                    break

                        if field_name and field_name not in fields_info["fields"]:
                            fields_info["fields"].append(field_name)

                            # 获取字段值作为示例
                            if hasattr(widget, 'field_value'):
                                field_value = widget.field_value
                                if field_value and field_name not in field_values:
                                    field_values[field_name] = str(field_value)
                                    if len(fields_info["sample_texts"]) < 10:  # 限制数量
                                        fields_info["sample_texts"][field_name] = str(field_value)
                    except Exception as e:
                        logger.debug(f"处理widget失败: {e}")

            # 如果没有找到表单字段，尝试从文本中提取可能的字段名和示例
            if not fields_info["fields"]:
                text_info = self._extract_fields_and_examples_from_text(doc)
                fields_info["fields"] = text_info.get("fields", [])
                fields_info["sample_texts"] = text_info.get("sample_texts", {})

            return fields_info

        finally:
            doc.close()

    def _extract_fields_and_examples_from_text(self, doc) -> Dict[str, Any]:
        """
        从文本中提取可能的字段名和示例值
        """
        result = {"fields": [], "sample_texts": {}}

        try:
            # 常见表单字段模式（字段名: 值）
            patterns = [
                (r'([A-Z_]{3,})\s*[:：]?\s*([^\n]+)', 'uppercase_field'),  # 大写字段
                (r'([\u4e00-\u9fa5]{2,6})\s*[:：]\s*([^\n]+)', 'chinese_field'),  # 中文字段
                (r'([A-Z][a-zA-Z0-9\s]+\s*[:：])\s*([^\n]+)', 'mixed_field'),  # 混合字段
            ]

            # 只检查前3页
            for page_num in range(min(3, len(doc))):
                page = doc[page_num]
                text = page.get_text("text")

                for pattern, pattern_type in patterns:
                    matches = re.findall(pattern, text)
                    for match in matches:
                        if isinstance(match, tuple) and len(match) >= 2:
                            field_name = match[0].strip('：: \n\t')
                            field_value = match[1].strip()

                            if (len(field_name) >= 2 and
                                    field_name not in result["fields"] and
                                    not field_name.isdigit()):

                                result["fields"].append(field_name)
                                if field_value and len(result["sample_texts"]) < 10:
                                    result["sample_texts"][field_name] = field_value

                            # 限制数量
                            if len(result["fields"]) >= 15:
                                return result

            return result

        except Exception as e:
            logger.error(f"提取字段和示例失败: {e}")
            return result

    def _extract_possible_fields_from_text(self, doc) -> Dict[str, Any]:
        """从文本中提取可能的字段名"""
        possible_fields = {"fields": []}

        try:
            # 只检查前3页
            for page_num in range(min(3, len(doc))):
                page = doc[page_num]
                text = page.get_text("text")

                # 查找可能的字段模式
                patterns = [
                    r'([A-Z_]{3,})',  # 大写和下划线
                    r'([A-Z][a-zA-Z0-9]+\s*:)',  # 单词后跟冒号
                    r'([\u4e00-\u9fa5]{2,5}\s*[：:])',  # 中文后跟冒号
                ]

                for pattern in patterns:
                    matches = re.findall(pattern, text)
                    for match in matches:
                        if isinstance(match, tuple):
                            match = match[0]

                        # 清理
                        clean_match = match.strip('：: \n\t')
                        if (len(clean_match) >= 2 and
                                clean_match not in possible_fields["fields"] and
                                not clean_match.isdigit()):
                            possible_fields["fields"].append(clean_match)

                # 限制数量
                if len(possible_fields["fields"]) > 20:
                    possible_fields["fields"] = possible_fields["fields"][:20]
                    break

            return possible_fields

        except Exception as e:
            logger.error(f"提取可能字段失败: {e}")
            return possible_fields

    def get_pdf_fonts(self, pdf_path: str) -> List[str]:
        """
        获取PDF中使用的字体列表
        """
        fonts_set = set()
        doc = fitz.open(pdf_path)

        try:
            # 只检查前5页
            for page_num in range(min(5, len(doc))):
                page = doc[page_num]

                try:
                    text_dict = page.get_text("dict")

                    for block in text_dict.get("blocks", []):
                        if "lines" in block:
                            for line in block["lines"]:
                                for span in line["spans"]:
                                    font = span.get("font", "")
                                    if font:
                                        fonts_set.add(font)
                except Exception as e:
                    logger.debug(f"第{page_num + 1}页字体分析失败: {e}")

            return sorted(list(fonts_set))

        finally:
            doc.close()


# 简单测试
def test_compatibility():
    """测试兼容性"""
    print("=== PDF处理器兼容性测试 ===")

    processor = PDFProcessor()

    # 创建一个简单的测试PDF
    test_pdf = "test_compatibility.pdf"

    # 清理旧文件
    if os.path.exists(test_pdf):
        os.remove(test_pdf)

    # 创建测试PDF
    doc = fitz.open()
    page = doc.new_page()

    # 添加一些文本
    page.insert_text((100, 100), "测试字段1: ____________", fontsize=12)
    page.insert_text((100, 130), "姓名: _________________", fontsize=12)
    page.insert_text((100, 160), "日期: 2024-01-01", fontsize=12)
    page.insert_text((100, 190), "PO_NO: PO20240001", fontsize=12)

    doc.save(test_pdf)
    doc.close()

    print(f"创建测试文件: {test_pdf}")

    # 测试字体检测
    print("\n1. 字体检测:")
    try:
        fonts = processor.get_pdf_fonts(test_pdf)
        print(f"  找到字体: {fonts}")
    except Exception as e:
        print(f"  字体检测失败: {e}")

    # 测试字段检测
    print("\n2. 字段检测:")
    try:
        fields = processor.detect_form_fields(test_pdf)
        print(f"  字段检测结果: {fields}")
    except Exception as e:
        print(f"  字段检测失败: {e}")

    # 测试文本替换
    print("\n3. 文本替换测试:")
    replacements = {
        "PO_NO": "PO20241234",
        "姓名": "张三",
        "日期": "2024-12-23"
    }

    try:
        output = processor.process_pdf(test_pdf, replacements)
        print(f"  ✓ 处理成功: {output}")
    except Exception as e:
        print(f"  ✗ 处理失败: {e}")

    # 清理
    if os.path.exists(test_pdf):
        os.remove(test_pdf)


if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 运行兼容性测试
    test_compatibility()