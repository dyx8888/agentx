from app.rag.smart_chunker import SmartChunker


def _chunks_by_type(chunks, chunk_type):
    return [chunk for chunk in chunks if chunk["metadata"]["chunk_type"] == chunk_type]


def test_product_description_keeps_heading_and_parameters_together():
    text = """商品说明：
灵鹿小黑瓶精华30ml，主打温和保湿和屏障护理。
规格：30ml正装；价格：199元；适用：换季干燥人群。
"""
    chunks = SmartChunker(max_chunk_chars=300).split_text(
        text,
        metadata={"source_file": "product.txt", "document_id": "doc-1"},
    )

    paragraph = _chunks_by_type(chunks, "paragraph")[0]
    assert "商品说明" in paragraph["content"]
    assert "规格：30ml正装" in paragraph["content"]
    assert paragraph["metadata"]["source_file"] == "product.txt"
    assert paragraph["metadata"]["document_id"] == "doc-1"
    assert paragraph["metadata"]["section_title"] == "商品说明："
    assert paragraph["metadata"]["chunk_index"] == 0


def test_after_sales_policy_keeps_conditions_and_exception_together():
    text = """售后政策：
适用条件：未拆封且不影响二次销售，支持7天无理由退货。
不适用条件：已拆封、缺少赠品或超过签收7天。
例外：质量问题由商家承担运费，平台规则优先。
"""
    chunks = SmartChunker(max_chunk_chars=360).split_text(text)

    rule = _chunks_by_type(chunks, "numbered_rule")[0]
    assert "适用条件" in rule["content"]
    assert "不适用条件" in rule["content"]
    assert "例外" in rule["content"]
    assert rule["metadata"]["has_policy_keywords"] is True
    assert rule["metadata"]["line_start"] == 2
    assert rule["metadata"]["line_end"] == 4


def test_platform_rule_keeps_banned_and_replacement_expression_together():
    text = """平台规则：
1. 禁用表达：医学级修复、永久美白、祛痘7天见效。
2. 替代表达：帮助维持肌肤屏障、保湿、妆前更服帖。
"""
    chunks = SmartChunker(max_chunk_chars=300).split_text(text)

    rule = _chunks_by_type(chunks, "numbered_rule")[0]
    assert "禁用表达" in rule["content"]
    assert "替代表达" in rule["content"]
    assert rule["metadata"]["chunk_type"] == "numbered_rule"


def test_update_notice_keeps_target_inventory_priority_and_effective_time():
    text = """更新公告：
目标：组合装A目标销量350套。
库存：组合装A保守可售库存调整为390套。
优先级：如与旧文件冲突，以更新公告为准。
生效时间：2026-08-19 10:00。
"""
    chunks = SmartChunker(max_chunk_chars=360).split_text(text)

    notice = _chunks_by_type(chunks, "update_notice")[0]
    assert "目标销量350套" in notice["content"]
    assert "保守可售库存调整为390套" in notice["content"]
    assert "以更新公告为准" in notice["content"]
    assert "2026-08-19" in notice["content"]
    assert notice["metadata"]["has_update_priority"] is True


def test_inventory_table_keeps_header_and_key_rows_together():
    text = """库存表：
SKU | 可售库存 | 安全库存 | 价格
组合装A | 390套 | 80套 | 259元
30ml正装 | 860瓶 | 180瓶 | 199元
"""
    chunks = SmartChunker(max_chunk_chars=320).split_text(text)

    table = _chunks_by_type(chunks, "table_like")[0]
    assert "SKU | 可售库存 | 安全库存 | 价格" in table["content"]
    assert "组合装A | 390套" in table["content"]
    assert "30ml正装 | 860瓶" in table["content"]
    assert table["metadata"]["has_table_like_rows"] is True


def test_faq_keeps_question_and_answer_together():
    text = """FAQ：
问：可以说医学级修复吗？
答：不能说医学级修复，可替换为帮助维持肌肤屏障。
"""
    chunks = SmartChunker(max_chunk_chars=300).split_text(text)

    faq = _chunks_by_type(chunks, "faq_pair")[0]
    assert "问：可以说医学级修复吗？" in faq["content"]
    assert "答：不能说医学级修复" in faq["content"]
    assert faq["metadata"]["section_title"] == "FAQ："


def test_fact_id_and_marker_are_captured_in_metadata():
    text = """测试事实：
fact_id=F_UPDATE_003 | marker=QPACK_UPDATE_003 | 实体=库存更新 | 数值=组合装A保守可售库存390套
"""
    chunks = SmartChunker(max_chunk_chars=300).split_text(text)

    fact = _chunks_by_type(chunks, "fact_line")[0]
    assert fact["metadata"]["fact_ids"] == ["F_UPDATE_003"]
    assert fact["metadata"]["markers"] == ["QPACK_UPDATE_003"]


def test_sop_metadata_lines_do_not_merge_fact_lines_into_fallback():
    text = """本文件为 public-demo synthetic 测试资料，不对应任何真实商家或个人。
文件名: 05_售后与客服SOP.txt
段落: 售后SOP
fact_id=F_SERVICE_001 | marker=QPACK_SERVICE_001 | 实体=七天无理由 | 数值=未拆封不影响二次销售支持7天无理由 | 时间范围=长期 | 限制条件=赠品需一并退回。
fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 实体=过敏反馈 | 数值=建议暂停使用并引导提供批号和照片 | 时间范围=长期 | 限制条件=不得诊断疾病。
fact_id=F_SERVICE_003 | marker=QPACK_SERVICE_003 | 实体=破损补发 | 数值=签收后48小时内反馈可补发 | 时间范围=长期 | 限制条件=需上传外箱照片。
fact_id=F_SERVICE_004 | marker=QPACK_SERVICE_004 | 实体=退款路径 | 数值=引导用户通过订单售后入口提交 | 时间范围=长期 | 限制条件=不得私下转账。
fact_id=F_SERVICE_005 | marker=QPACK_SERVICE_005 | 实体=客服响应 | 数值=工作日2小时内首次响应 | 时间范围=长期 | 限制条件=高峰期可延长至4小时。
fact_id=F_SERVICE_006 | marker=QPACK_SERVICE_006 | 实体=赠品缺失 | 数值=优先补发洁面小样 | 时间范围=长期 | 限制条件=需核对订单活动资格。
fact_id=F_SERVICE_007 | marker=QPACK_SERVICE_007 | 实体=预售延迟 | 数值=超承诺发货24小时主动告知并补偿10元券 | 时间范围=预售期 | 限制条件=需用户未申请退款。
"""
    chunks = SmartChunker(max_chunk_chars=260).split_text(text)

    service_002 = [
        chunk for chunk in chunks if "F_SERVICE_002" in chunk["metadata"].get("fact_ids", [])
    ]
    service_006 = [
        chunk for chunk in chunks if "F_SERVICE_006" in chunk["metadata"].get("fact_ids", [])
    ]

    assert len(service_002) == 1
    assert service_002[0]["metadata"]["chunk_type"] == "fact_line"
    assert service_002[0]["metadata"]["markers"] == ["QPACK_SERVICE_002"]
    assert len(service_006) == 1
    assert service_006[0]["metadata"]["chunk_type"] == "fact_line"
    assert service_006[0]["metadata"]["markers"] == ["QPACK_SERVICE_006"]
    assert not any(
        chunk["metadata"]["chunk_type"] == "fallback"
        and "F_SERVICE_001" in chunk["content"]
        and "F_SERVICE_007" in chunk["content"]
        for chunk in chunks
    )


def test_unstructured_long_text_falls_back_to_recursive_chunks():
    text = "这是一段没有标题和结构的长文本。" * 80
    chunks = SmartChunker(max_chunk_chars=180, fallback_chunk_overlap=20).split_text(text)

    assert len(chunks) > 1
    assert all(chunk["metadata"]["chunk_type"] == "fallback" for chunk in chunks)
    assert all(len(chunk["content"]) <= 180 for chunk in chunks)


def test_oversized_semantic_unit_is_split_with_reasonable_limit():
    text = "商品说明：\n" + ("温和保湿屏障护理，适合换季干燥人群。" * 80)
    chunks = SmartChunker(max_chunk_chars=160, fallback_chunk_overlap=16).split_text(text)

    assert len(chunks) > 1
    assert all(len(chunk["content"]) <= 160 for chunk in chunks)
    assert all(chunk["metadata"]["line_start"] == 2 for chunk in chunks)


def test_metadata_records_line_and_character_positions():
    text = "商品说明：\n灵鹿小黑瓶精华30ml。\n"
    chunks = SmartChunker(max_chunk_chars=200).split_text(text)
    chunk = chunks[0]
    metadata = chunk["metadata"]

    assert metadata["chunk_type"] == "paragraph"
    assert metadata["line_start"] == 2
    assert metadata["line_end"] == 2
    assert metadata["char_start"] == text.index("灵鹿")
    assert metadata["char_end"] == len(text.rstrip("\n"))
