# -*- coding: utf-8 -*-
"""
Advisor 使用示例
演示如何在 pH 控制项目中使用 DeepSeek Advisor
"""
import json
import os
import sys
from advisor import (
    DeepSeekAdvisor,
    AdvisorConfig,
    AdvisorRole,
    AdviceQuality,
    AdviceRequest,
    create_advisor,
    debug_code,
    quick_ask,
    AsyncAdvisorQueue,
)


def load_config() -> dict:
    """加载配置"""
    config_file = "advisor_config.json"
    if not os.path.exists(config_file):
        config_file = "advisor_config_example.json"
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"加载配置失败: {e}")
        return {}


def example_1_basic_usage():
    """示例1: 基础使用"""
    print("=" * 60)
    print("示例1: 基础使用")
    print("=" * 60)

    config = load_config()
    api_key = config.get("api_key", "")

    if not api_key or api_key == "your-deepseek-api-key-here":
        print("请先配置 advisor_config.json 中的 API 密钥")
        return

    # 创建顾问
    advisor = create_advisor(
        api_key=api_key,
        base_url=config.get("base_url", "https://api.deepseek.com"),
        model=config.get("model", "deepseek-chat"),
    )

    # 快速提问
    response = quick_ask(
        advisor=advisor,
        query="Python中如何实现PID控制？",
        role=AdvisorRole.CODE_DEBUGGER,
    )

    if response.success:
        print(f"回答:\n{response.content}")
        print(f"\n使用token: {response.tokens_used}")
        print(f"耗时: {response.latency:.2f}s")
    else:
        print(f"错误: {response.error}")


def example_2_code_debugging():
    """示例2: 代码调试"""
    print("\n" + "=" * 60)
    print("示例2: 代码调试")
    print("=" * 60)

    config = load_config()
    api_key = config.get("api_key", "")

    if not api_key or api_key == "your-deepseek-api-key-here":
        return

    advisor = create_advisor(api_key=api_key)

    # 假设有问题的代码
    problematic_code = """
def calculate_ph(orp_mv, k, b):
    # 这段代码有问题
    ph = orp_mv * k
    if ph > 14:
        ph = 14
    return ph
    """

    error_message = "TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'"

    response = debug_code(
        advisor=advisor,
        code=problematic_code,
        error_msg=error_message,
        expected_behavior="应该正确处理 None 值，返回合理的 pH 值",
    )

    if response.success:
        print(f"调试建议:\n{response.content}")
    else:
        print(f"错误: {response.error}")


def example_3_ph_control_advice():
    """示例3: pH控制专家建议"""
    print("\n" + "=" * 60)
    print("示例3: pH控制专家建议")
    print("=" * 60)

    config = load_config()
    api_key = config.get("api_key", "")

    if not api_key or api_key == "your-deepseek-api-key-here":
        return

    advisor = create_advisor(api_key=api_key)

    # 提供实验上下文
    context = {
        "current_ph": 3.2,
        "target_ph": 5.0,
        "orp_reading": -150,  # mV
        "pump_flow_rate": 0.5,  # ml/s
        "recent_trend": "pH缓慢上升",
        "problem": "滴定速度太慢，需要30分钟才能达到目标",
    }

    request = AdviceRequest(
        query="请分析当前的pH控制情况，提供优化建议。",
        context=context,
        role=AdvisorRole.PH_CONTROL_EXPERT,
        quality=AdviceQuality.DETAILED,
    )

    response = advisor.ask(request)

    if response.success:
        print(f"专家建议:\n{response.content}")
    else:
        print(f"错误: {response.error}")


def example_4_async_usage():
    """示例4: 异步使用"""
    print("\n" + "=" * 60)
    print("示例4: 异步使用")
    print("=" * 60)

    config = load_config()
    api_key = config.get("api_key", "")

    if not api_key or api_key == "your-deepseek-api-key-here":
        return

    advisor = create_advisor(api_key=api_key)

    # 定义回调函数
    def on_advice(response):
        print("\n收到异步响应:")
        if response.success:
            print(response.content[:200] + "...")
        else:
            print(f"错误: {response.error}")

    # 异步提问
    print("发送异步请求...")
    thread = advisor.ask_async(
        request=AdviceRequest(
            query="如何优化Arduino的串口通信？",
            role=AdvisorRole.CODE_DEBUGGER,
        ),
        callback=on_advice,
    )

    # 可以继续做其他事情
    print("主线程继续执行其他任务...")
    thread.join(timeout=10)
    print("异步示例完成")


def example_5_data_analysis():
    """示例5: 数据分析"""
    print("\n" + "=" * 60)
    print("示例5: 数据分析")
    print("=" * 60)

    config = load_config()
    api_key = config.get("api_key", "")

    if not api_key or api_key == "your-deepseek-api-key-here":
        return

    advisor = create_advisor(api_key=api_key)

    # 模拟实验数据
    context = {
        "data_points": [
            {"time": "00:00", "ph": 3.0, "orp": -200},
            {"time": "00:05", "ph": 3.5, "orp": -180},
            {"time": "00:10", "ph": 4.0, "orp": -150},
            {"time": "00:15", "ph": 4.3, "orp": -130},
            {"time": "00:20", "ph": 4.5, "orp": -120},
        ],
        "calibration_date": "2026-06-01",
        "sample_type": "废水",
    }

    request = AdviceRequest(
        query="请分析这些pH/ORP数据，识别任何异常或趋势，"
              "并建议下一步的实验方案。",
        context=context,
        role=AdvisorRole.DATA_ANALYST,
        quality=AdviceQuality.DETAILED,
    )

    response = advisor.ask(request)

    if response.success:
        print(f"分析报告:\n{response.content}")
    else:
        print(f"错误: {response.error}")


def main():
    """主函数"""
    print("DeepSeek Advisor 使用示例\n")

    # 显示可用示例
    examples = [
        ("基础使用", example_1_basic_usage),
        ("代码调试", example_2_code_debugging),
        ("pH控制专家", example_3_ph_control_advice),
        ("异步使用", example_4_async_usage),
        ("数据分析", example_5_data_analysis),
    ]

    print("可用示例:")
    for i, (name, _) in enumerate(examples, 1):
        print(f"  {i}. {name}")
    print()

    # 运行所有示例
    for name, func in examples:
        try:
            func()
        except KeyboardInterrupt:
            print("\n用户中断")
            break
        except Exception as e:
            print(f"\n示例 '{name}' 出错: {e}")
            import traceback
            traceback.print_exc()

    print("\n示例运行完成")


if __name__ == "__main__":
    main()
