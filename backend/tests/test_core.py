"""
智答引擎（ZhiDa Engine）—— 核心模块测试

测试不需要外部依赖（LLM/数据库/向量库）的模块。
"""

import sys
import os

# 确保 backend 在 path 中
# 本文件位于 backend/tests/，需要添加 backend/ 的父目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ================================================================
# 测试 1: 配置模块
# ================================================================
print("=" * 60)
print("测试 1: 配置模块 (app.core.config)")
print("=" * 60)

try:
    from app.core.config import settings, get_app_data_dir

    print(f"  ✅ APP_NAME: {settings.APP_NAME}")
    print(f"  ✅ APP_VERSION: {settings.APP_VERSION}")
    print(f"  ✅ DATA_DIR: {settings.DATA_DIR}")
    print(f"  ✅ db_url: {settings.db_url}")
    print(f"  ✅ chroma_dir: {settings.chroma_dir}")
    print(f"  ✅ cache_dir: {settings.cache_dir}")
    print(f"  ✅ API_HOST: {settings.API_HOST}:{settings.API_PORT}")

    # 模块开关
    print(f"  ✅ ENABLE_SINGLE_FLIGHT: {settings.ENABLE_SINGLE_FLIGHT}")
    print(f"  ✅ ENABLE_STREAMING: {settings.ENABLE_STREAMING}")
    print(f"  ✅ ENABLE_SOURCE_CITATION: {settings.ENABLE_SOURCE_CITATION}")

    print("  ✅ 配置模块测试通过")
except Exception as e:
    print(f"  ❌ 配置模块测试失败: {e}")
    import traceback; traceback.print_exc()

# ================================================================
# 测试 2: 厂商模板数据结构
# ================================================================
print("\n" + "=" * 60)
print("测试 2: 厂商模板数据结构 (provider_templates)")
print("=" * 60)

try:
    from app.services.llm.provider_templates import (
        BUILTIN_PROVIDER_TEMPLATES,
        ProviderCategory,
        ProviderTemplate,
        get_provider_by_id,
        get_cloud_providers,
        get_local_providers,
        get_all_provider_ids,
    )

    # 检查模板数量
    print(f"  ✅ 内置模板总数: {len(BUILTIN_PROVIDER_TEMPLATES)}")

    # 按分类统计
    cloud = get_cloud_providers()
    local = get_local_providers()
    print(f"  ✅ 云端厂商: {len(cloud)} 个")
    print(f"  ✅ 本地厂商: {len(local)} 个")

    # 检查每个模板的关键字段
    for t in BUILTIN_PROVIDER_TEMPLATES:
        assert t.provider_id, f"{t.name}: provider_id 为空"
        assert t.name, f"name 为空"
        assert t.category in (ProviderCategory.CLOUD, ProviderCategory.LOCAL, ProviderCategory.CUSTOM), f"{t.name}: 无效分类"
        assert t.default_model or t.provider_id == "custom", f"{t.name}: default_model 为空"
        assert t.base_url or t.provider_id == "custom", f"{t.name}: base_url 为空"
        print(f"  ✅ {t.icon} {t.name} ({t.provider_id}): {t.default_model}")

    # 测试查询函数
    ds = get_provider_by_id("deepseek")
    assert ds is not None
    assert ds.name == "DeepSeek"
    assert ds.default_model == "deepseek-v4-pro"
    print(f"  ✅ 按 ID 查询 DeepSeek: {ds.name} / {ds.default_model}")

    ollama = get_provider_by_id("ollama")
    assert ollama is not None
    assert ollama.requires_api_key == False
    print(f"  ✅ Ollama 不需要 API Key: {ollama.requires_api_key}")

    custom = get_provider_by_id("custom")
    assert custom is not None
    assert custom.base_url == ""
    print(f"  ✅ 自定义模板: base_url 为空（{custom.base_url == ''}）")

    ids = get_all_provider_ids()
    assert "deepseek" in ids
    assert "ollama" in ids
    assert "custom" in ids
    print(f"  ✅ 所有厂商 ID: {ids}")

    print("  ✅ 厂商模板测试通过")
except Exception as e:
    print(f"  ❌ 厂商模板测试失败: {e}")
    import traceback; traceback.print_exc()

# ================================================================
# 测试 3: 限流器
# ================================================================
print("\n" + "=" * 60)
print("测试 3: 限流器 (rate_limiter)")
print("=" * 60)

try:
    from app.services.cache.rate_limiter import (
        TokenBucket,
        SlidingWindow,
        QuestionCooldown,
        RateLimiter,
        RateLimitResult,
        RateLimitConfig,
    )

    # 令牌桶测试
    bucket = TokenBucket(rate=10, capacity=3)
    assert bucket.consume(), "第一次消费应成功"
    assert bucket.consume(), "第二次消费应成功"
    assert bucket.consume(), "第三次消费应成功"
    assert not bucket.consume(), "第四次消费应失败（桶空）"
    print(f"  ✅ 令牌桶: 消费 3 次后桶空")

    # 滑动窗口测试
    window = SlidingWindow(window_size=60, max_requests=3)
    assert window.allow(), "第 1 次应允许"
    assert window.allow(), "第 2 次应允许"
    assert window.allow(), "第 3 次应允许"
    assert not window.allow(), "第 4 次应拒绝"
    print(f"  ✅ 滑动窗口: 窗口内 3 次后拒绝")

    # 问题冷却测试
    cooldown = QuestionCooldown(cooldown_seconds=300)
    assert not cooldown.is_cooling_down("hash_1"), "首次不应冷却"
    cooldown.mark_answered("hash_1")
    assert cooldown.is_cooling_down("hash_1"), "标记后应冷却"
    assert not cooldown.is_cooling_down("hash_2"), "不同问题不应冷却"
    print(f"  ✅ 问题冷却: 相同问题冷却，不同问题不冷却")

    # 多层限流器测试
    limiter = RateLimiter()
    result = limiter.check("chat_001", "test_hash", is_private=False)
    assert result == RateLimitResult.ALLOW, f"应允许，实际: {result}"
    limiter.record("chat_001", "test_hash")
    print(f"  ✅ 多层限流器: 首次请求允许")

    # 私聊放宽测试
    result_private = limiter.check("chat_002", "test_hash_2", is_private=True)
    assert result_private == RateLimitResult.ALLOW
    print(f"  ✅ 私聊限流: 允许（放宽限制）")

    # 统计测试
    stats = limiter.get_stats("chat_001")
    assert "available_tokens" in stats
    assert "window_requests" in stats
    print(f"  ✅ 限流统计: {stats}")

    print("  ✅ 限流器测试通过")
except Exception as e:
    print(f"  ❌ 限流器测试失败: {e}")
    import traceback; traceback.print_exc()

# ================================================================
# 测试 4: 降级管理器
# ================================================================
print("\n" + "=" * 60)
print("测试 4: 降级管理器 (degradation)")
print("=" * 60)

try:
    import asyncio
    from app.services.cache.degradation import (
        DegradationManager,
        DegradationLevel,
    )

    async def _test_degradation():
        dm = DegradationManager()

        # 正常执行
        async def test_primary():
            return "主策略成功"

        result = await dm.execute_with_fallback(
            service="test",
            primary=test_primary,
            fallbacks=[],
            offline_response="兜底",
        )
        assert result == "主策略成功", f"期望 '主策略成功', 实际 '{result}'"
        assert dm.is_healthy("test")
        print(f"  ✅ 主策略成功: {result}")

        # 主策略失败 → 降级
        async def test_primary_fail():
            raise RuntimeError("主策略失败")

        async def test_fallback():
            return "降级策略成功"

        result2 = await dm.execute_with_fallback(
            service="test2",
            primary=test_primary_fail,
            fallbacks=[test_fallback],
            offline_response="兜底",
        )
        assert result2 == "降级策略成功"
        assert dm.get_level("test2") == DegradationLevel.DEGRADED
        print(f"  ✅ 降级策略成功: {result2}")

        # 全部失败 → 兜底
        async def test_fallback_fail():
            raise RuntimeError("降级也失败")

        result3 = await dm.execute_with_fallback(
            service="test3",
            primary=test_primary_fail,
            fallbacks=[test_fallback_fail],
            offline_response="离线兜底回复",
        )
        assert result3 == "离线兜底回复"
        assert dm.get_level("test3") == DegradationLevel.OFFLINE
        print(f"  ✅ 离线兜底: {result3}")

        # 降级事件
        events = dm.get_events()
        assert len(events) >= 2
        print(f"  ✅ 降级事件记录: {len(events)} 条")

        # 离线回复
        offline = DegradationManager.get_llm_offline_response()
        assert "AI 助手" in offline
        print(f"  ✅ LLM 离线兜底回复: {offline[:50]}...")

        print("  ✅ 降级管理器测试通过")

    asyncio.run(_test_degradation())
except Exception as e:
    print(f"  ❌ 降级管理器测试失败: {e}")
    import traceback; traceback.print_exc()

# ================================================================
# 测试 5: Single-Flight 幂等控制
# ================================================================
print("\n" + "=" * 60)
print("测试 5: Single-Flight (idempotency)")
print("=" * 60)

try:
    import asyncio
    from app.services.cache.idempotency import SingleFlight

    sf = SingleFlight(cache_dir=settings.cache_dir)

    call_counter = [0]  # 使用列表避免 nonlocal 作用域问题

    async def slow_fn(sleep_time: float = 0.1):
        call_counter[0] += 1
        await asyncio.sleep(sleep_time)
        return f"result_{call_counter[0]}"

    # 并发调用相同 key
    async def test_concurrent():
        tasks = [
            sf.do("test_key", slow_fn, 0.1)
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks)
        return results

    results = asyncio.run(test_concurrent())
    assert call_counter[0] == 1, f"期望 1 次调用，实际 {call_counter[0]} 次"
    assert all(r == "result_1" for r in results), f"所有结果应相同: {results}"
    print(f"  ✅ Single-Flight: 5 个并发请求合并为 1 次调用, 结果: {results}")

    print("  ✅ Single-Flight 测试通过")
except Exception as e:
    print(f"  ❌ Single-Flight 测试失败: {e}")
    import traceback; traceback.print_exc()

# ================================================================
# 测试 6: 查询缓存
# ================================================================
print("\n" + "=" * 60)
print("测试 6: 查询缓存 (query_cache)")
print("=" * 60)

try:
    from app.services.cache.query_cache import QueryCache

    import tempfile
    import shutil
    tmp_dir = tempfile.mkdtemp()
    cache = QueryCache(cache_dir=tmp_dir)

    async def _test_cache():
        # 缓存未命中
        result = await cache.get("这是一个测试问题")
        assert result is None, f"首次查询应未命中，实际: {result}"
        print(f"  ✅ 缓存未命中: {result}")

        # 写入缓存
        await cache.set("这是一个测试问题", "这是测试答案")
        print(f"  ✅ 缓存写入: 问题 → 答案")

        # 缓存命中
        result = await cache.get("这是一个测试问题")
        assert result == "这是测试答案", f"应命中缓存，实际: {result}"
        print(f"  ✅ 缓存命中: {result}")

        # 相似问题（相同语义）
        result2 = await cache.get("这是  一个  测试     问题")
        assert result2 == "这是测试答案", f"归一化后应命中缓存，实际: {result2}"
        print(f"  ✅ 归一化匹配: 多余空白不影响匹配")

        # 缓存失效
        await cache.invalidate("这是一个测试问题")
        result3 = await cache.get("这是一个测试问题")
        assert result3 is None, f"失效后应未命中，实际: {result3}"
        print(f"  ✅ 缓存失效: {result3}")

        # 统计
        stats = cache.stats
        print(f"  ✅ 缓存统计: hits={stats['hits']}, misses={stats['misses']}, hit_rate={stats['hit_rate']}%")

        # 清理
        await cache.clear()

    asyncio.run(_test_cache())
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print("  ✅ 查询缓存测试通过")
except Exception as e:
    print(f"  ❌ 查询缓存测试失败: {e}")
    import traceback; traceback.print_exc()

# ================================================================
# 测试 7: 文档解析器
# ================================================================
print("\n" + "=" * 60)
print("测试 7: 文档解析器 (parser)")
print("=" * 60)

try:
    from app.services.knowledge.parser import DocumentParser, FileType, ParseStatus

    parser = DocumentParser()

    # 测试 TXT 解析
    txt_content = "这是第一行\n\n这是第二行\n\n这是第三行"
    txt_path = "/tmp/test_zhida.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_content)

    async def _test_parse():
        result = await parser.parse(txt_path)
        assert result.status == ParseStatus.SUCCESS
        assert "这是第一行" in result.text
        assert result.parse_time_ms > 0
        print(f"  ✅ TXT 解析: {len(result.text)} 字符, 耗时 {result.parse_time_ms:.0f}ms")
        return result

    result = asyncio.run(_test_parse())

    # 文件类型检测
    ft = parser.get_file_type(txt_path)
    assert ft == FileType.TXT
    print(f"  ✅ 文件类型检测: {ft.value}")

    # 清理
    os.remove(txt_path)

    print("  ✅ 文档解析器测试通过")
except Exception as e:
    print(f"  ❌ 文档解析器测试失败: {e}")
    import traceback; traceback.print_exc()

# ================================================================
# 测试 8: 文本切片器
# ================================================================
print("\n" + "=" * 60)
print("测试 8: 文本切片器 (splitter)")
print("=" * 60)

try:
    from app.services.knowledge.splitter import TextSplitter, TextChunk

    splitter = TextSplitter(chunk_size=200, overlap=20)

    # 固定大小切片
    long_text = "这是一个测试文本。" * 50
    chunks = splitter.split_fixed(long_text)
    assert len(chunks) > 0, "切片不应为空"
    assert all(isinstance(c, TextChunk) for c in chunks)
    print(f"  ✅ 固定大小切片: {len(chunks)} 个切片")

    # 语义分块
    md_text = """## 标题一
这是第一段内容。

这是第一段的第二段。

## 标题二
这是第二段的内容。"""
    semantic_chunks = splitter.split_semantic(md_text)
    assert len(semantic_chunks) > 0
    print(f"  ✅ 语义分块: {len(semantic_chunks)} 个切片")

    # 小切片合并
    small_chunks = [
        TextChunk(text="短", chunk_index=0),
        TextChunk(text="也是短的", chunk_index=1),
        TextChunk(text="这是一个足够长的文本块，用来测试合并逻辑是否正常工作", chunk_index=2),
    ]
    merged = splitter.merge_small_chunks(small_chunks, min_chunk_size=10)
    print(f"  ✅ 小切片合并: {len(small_chunks)} → {len(merged)} 个切片")

    print("  ✅ 文本切片器测试通过")
except Exception as e:
    print(f"  ❌ 文本切片器测试失败: {e}")
    import traceback; traceback.print_exc()

# ================================================================
# 测试 9: Prompt 模板
# ================================================================
print("\n" + "=" * 60)
print("测试 9: Prompt 模板 (prompt)")
print("=" * 60)

try:
    from app.services.qa.prompt import PromptTemplate, prompt_template

    # 默认问答 Prompt
    prompt = prompt_template.build_qa_prompt(
        question="退换货政策是什么？",
        context="参考知识：支持7天无理由退换货。",
        include_sources=False,
    )
    assert "退换货政策是什么" in prompt
    assert "参考知识" in prompt
    assert "不要编造信息" in prompt
    print(f"  ✅ 默认问答 Prompt: {len(prompt)} 字符")

    # 带来源引用
    prompt_with_source = prompt_template.build_qa_prompt(
        question="退换货政策是什么？",
        context="参考知识：支持7天无理由退换货。",
        source_info="来源: 退换货政策文档",
        include_sources=True,
    )
    assert "来源" in prompt_with_source
    print(f"  ✅ 来源引用 Prompt: {len(prompt_with_source)} 字符")

    # 电商客服 Prompt
    ecom = prompt_template.build_ecommerce_prompt(
        question="这件衣服是什么材质？",
        context="商品材质：100%纯棉。",
    )
    assert "电商客服" in ecom
    assert "纯棉" in ecom
    print(f"  ✅ 电商客服 Prompt: {len(ecom)} 字符")

    # 上下文构建
    # 使用简单 mock 避免导入 chromadb 依赖
    from dataclasses import dataclass
    @dataclass
    class MockIndexResult:
        chunk_id: str
        text: str
        metadata: dict
        score: float = 0.0

    results = [
        MockIndexResult(chunk_id="1", text="第一段参考内容", metadata={"filename": "doc1.pdf"}, score=0.9),
        MockIndexResult(chunk_id="2", text="第二段参考内容", metadata={"section_title": "政策说明"}, score=0.8),
    ]
    context = PromptTemplate.build_context_from_results(results)
    assert "第一段参考内容" in context
    assert "第二段参考内容" in context
    print(f"  ✅ 上下文构建: {len(context)} 字符")

    print("  ✅ Prompt 模板测试通过")
except Exception as e:
    print(f"  ❌ Prompt 模板测试失败: {e}")
    import traceback; traceback.print_exc()

# ================================================================
# 总结
# ================================================================
print("\n" + "=" * 60)
print("测试总结")
print("=" * 60)
print("所有核心模块测试完成！")
print("测试覆盖: 配置/厂商模板/限流器/降级/Single-Flight/缓存/文档解析/切片/Prompt")
print("未测试（需要外部依赖）: LLM网关/向量化/索引/检索器/生成器")
