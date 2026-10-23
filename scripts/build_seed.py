"""Build page-linked reader seeds from the existing, reviewed Chinese notes.

Source PDFs and Markdown notes are read-only inputs. Page ranges are curated
below, not inferred as claims of page-by-page review.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pypdf import PdfReader


PROJECT = Path(__file__).resolve().parents[1]
LIBRARY = PROJECT.parent / "第一批文献"
NOTES = LIBRARY / "阅读笔记"
KINDS = {"guide", "concept", "method", "experiment", "critique", "note"}


def read_note(name: str) -> str:
    return (NOTES / name).read_text(encoding="utf-8-sig")


def section(text: str, prefix: str) -> tuple[str, str]:
    matches = list(re.finditer(r"(?m)^## (.+)$", text))
    for index, match in enumerate(matches):
        if match.group(1).startswith(prefix):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            return match.group(1), text[match.end():end].strip()
    raise ValueError(f"Missing section: {prefix}")


def blocks(text: str) -> dict[str, str]:
    if re.search(r"(?m)^### ", text):
        pattern = r"(?m)^(?:### (.+)$|\*\*((?:阅读路径|带读路径|阅读路线|带读路线|自测|自测题)[。:：]?)\*\*[ \t]*)"
    else:
        pattern = r"(?m)^\*\*([^*\n]+)\*\*\s*"
    matches = list(re.finditer(pattern, text))
    result = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        label = next(group for group in match.groups() if group).strip().rstrip("。:：")
        result[label] = text[match.end():end].strip()
    return result


def clean_content(content: str) -> str:
    # Browser navigation uses page_start; absolute filesystem links are prose.
    def local_reference(match: re.Match) -> str:
        label, target = match.groups()
        suffix = "（见右侧原文）" if target.rstrip("> ").lower().endswith(".pdf") else "（阅读笔记）"
        return label + suffix

    content = re.sub(r"\[([^\]]+)\]\(<?([A-Za-z]:[/\\][^)]+)>?\)", local_reference, content)
    content = re.sub(r"```mermaid\s*.*?```", "简图：输入 → 前置层 → 分支一 / 分支二 → 汇合层 → 输出。", content, flags=re.S)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def note(title: str, pages: tuple[int, int], kind: str, content: str) -> dict:
    if not content.strip():
        raise ValueError(f"Empty note: {title}")
    return {
        "title": title,
        "page_start": pages[0],
        "page_end": pages[1],
        "kind": kind,
        "content": clean_content(content),
        "sort_order": 0,
        "completed": False,
    }


def joined(source: dict[str, str], *labels: str) -> str:
    return "\n\n".join(f"### {label}\n\n{source[label]}" for label in labels)


def split_once(text: str, marker: str) -> tuple[str, str]:
    before, found, after = text.partition(marker)
    if not found:
        raise ValueError(f"Missing split marker: {marker}")
    return before.strip(), (marker + after).strip()


def numbered_experiments(text: str) -> tuple[str, str]:
    first, second = split_once(text, "\n2. ")
    return re.sub(r"^1\.\s*", "", first), re.sub(r"^2\.\s*", "", second)


def build() -> list[dict]:
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    texts = {
        "foundation": read_note("02_分割与排队基础.md"),
        "dynamic": read_note("03_动态控制与稳定性.md"),
        "game": read_note("04_博弈与带宽分配.md"),
        "mobile": read_note("05_移动网络与不确定性.md"),
        "lesson": read_note("01_第一讲_QDMP带读.md"),
    }
    papers: list[dict] = []

    def add(slug, title, short_title, authors, venue, year, tags, filename, source, prefix, entries, overview):
        _, source_text = section(texts[source], prefix)
        b = blocks(source_text)
        route_label = next((label for label in ("阅读路径", "带读路径", "阅读路线", "带读路线") if label in b), None)
        overview_text = "版本：批量简要导读，尚非逐篇精读稿。\n\n" + overview + "\n\n核验范围：核心模型、算法和实验；未逐项重证全部定理，未复现作者代码。页码为PDF文件页码。"
        if route_label:
            overview_text += "\n\n### 建议阅读路线\n\n" + b[route_label]
        parsed = [note("导读：" + short_title, (1, 1), "guide", overview_text)]
        parsed.extend(entries(b))
        pdf_path = LIBRARY / filename
        if not pdf_path.is_file():
            raise FileNotFoundError(pdf_path)
        page_count = len(PdfReader(str(pdf_path)).pages)
        for index, item in enumerate(parsed):
            item["sort_order"] = index
            if item["kind"] not in KINDS or not 1 <= item["page_start"] <= item["page_end"] <= page_count:
                raise ValueError(f"Invalid note range/kind: {slug}: {item}")
            if re.search(r"\]\(<?[A-Za-z]:[/\\]", item["content"]):
                raise ValueError(f"Unconverted local Markdown link: {slug}")
        source_name = {
            "foundation": "02_分割与排队基础.md", "dynamic": "03_动态控制与稳定性.md",
            "game": "04_博弈与带宽分配.md", "mobile": "05_移动网络与不确定性.md",
        }[source]
        source_files = ["00_阅读导航与总览.md", source_name]
        if slug == "qdmp":
            source_files.append("01_第一讲_QDMP带读.md")
        for name in source_files:
            if not (NOTES / name).is_file():
                raise FileNotFoundError(NOTES / name)
        papers.append({
            "id": slug, "title": title, "short_title": short_title,
            "authors": authors, "venue": venue, "year": year, "tags": tags,
            "pdf_path": str(pdf_path.resolve()), "page_count": page_count,
            "sourceNotes": [str((NOTES / name).resolve()) for name in source_files],
            "notes": parsed,
        })

    def qdmp_entries(b):
        specs = [
            ("第一步", (2, 2), "concept"), ("第二步", (7, 7), "concept"),
            ("第三步", (7, 8), "concept"), ("第四步", (7, 9), "method"),
            ("第五步", (10, 13), "method"), ("第六步", (5, 9), "method"),
            ("第七步", (14, 17), "experiment"), ("第八步", (20, 21), "guide"),
        ]
        result = []
        for prefix, pages, kind in specs:
            title, content = section(texts["lesson"], prefix)
            result.append(note(title, pages, kind, content))
        result.append(note("适用边界与复现核验", (8, 21), "critique", b["对你的课题的用法与边界"]))
        return result

    add("qdmp", "Towards Real-time Cooperative Deep Inference over the Cloud and Edge End Devices", "QDMP",
        "Shigeng Zhang, Yinggang Li, Xuan Liu, Song Guo, Weiping Wang, Jianxin Wang, Bo Ding, Di Wu",
        "ACM IMWUT 4(2), Article 69", 2020, ["DAG分割", "最小割", "代价测量", "研究一"],
        "3397315.pdf", "foundation", "1. QDMP", qdmp_entries,
        "先理解单次推理的计算/通信代价，再理解割点如何组织局部最小割。第一讲的八个步骤已按原文主题定位；其中手算数据明确为教学构造，并非作者实验。")

    def jpdra_entries(b):
        basic, tandem = split_once(b["模型与关键公式"], "**串联近似需读仔细。**")
        return [
            note("问题：从单帧服务到持续任务流", (1, 2), "concept", b["研究的问题"]),
            note("到达率、服务率与M/D/1时延", (3, 5), "concept", basic),
            note("串联下游到达为何只是近似", (4, 4), "critique", tandem),
            note("部署、资源分解与SPDRA流程", (5, 8), "method", b["优化与算法"]),
            note("仿真：求解开销与分项时延", (8, 11), "experiment", b["实验真正支持什么"]),
            note("迁移边界与算法方向核验", (5, 11), "critique", b["对你的课题的用法与边界"]),
        ]

    add("jpdra", "Joint DNN Partition Deployment and Resource Allocation for Delay-Sensitive Deep Learning Inference in IoT", "JPDRA / SPDRA",
        "Wenchen He, Shaoyong Guo, Song Guo, Xuesong Qiu, Feng Qi", "IEEE IoTJ 7(10):9241–9254", 2020,
        ["串联排队", "部署", "资源分配", "研究一"],
        "Joint_DNN_Partition_Deployment_and_Resource_Allocation_for_Delay-Sensitive_Deep_Learning_Inference_in_IoT.pdf",
        "foundation", "2. JPDRA", jpdra_entries,
        "重点区分每项任务的服务时间与等待时间，并辨认给定候选分区之后的部署、算力决策。JPDRA是问题名称，SPDRA是主要低开销算法。")

    def dynamic_entries(b, ranges):
        formula_label = "核心公式"
        method_label = next(label for label in b if label.startswith("算法与保证"))
        labels = [
            ("问题与系统假设", "concept", ("一句话问题", "系统和假设")),
            ("决策、目标与约束", "concept", (next(label for label in b if label.startswith("决策与")),)),
            ("核心队列与代价公式", "concept", (formula_label,)),
            ("求解流程与理论覆盖范围", "method", (method_label,)),
            ("两个有条件的实验发现", "experiment", ("两个实验发现",)),
            ("迁移判断与未解决问题", "critique", ("迁移判断",)),
        ]
        return [note(title, pages, kind, joined(b, *keys)) for (title, kind, keys), pages in zip(labels, ranges, strict=True)]

    add("cutedge", "Cutting-Edge Inference: Dynamic DNN Model Partitioning and Resource Scaling for Mobile AI", "CutEdge",
        "Jeong-A Lim, Joohyun Lee, Jeongho Kwak, Yeongjin Kim", "IEEE TSC 17(6):3300–3316", 2024,
        ["虚拟队列", "Lyapunov", "动态控制", "研究一"],
        "Cutting-Edge_Inference_Dynamic_DNN_Model_Partitioning_and_Resource_Scaling_for_Mobile_AI.pdf",
        "dynamic", "CutEdge", lambda b: dynamic_entries(b, [(4, 7), (7, 7), (6, 8), (8, 10), (12, 15), (7, 15)]),
        "先区分平均指标的虚拟欠账与真实图像缓存，再看切点、处理帧数和GPU频率如何联合控制。本文没有用RL求解逐时隙问题。")

    add("lyappo", "Energy Optimization of Multitask DNN Inference in MEC-Assisted XR Devices: A Lyapunov-Guided Reinforcement Learning Approach", "LyaPPO",
        "Yanzan Sun, Jiacheng Qiu, Guangjin Pan, Shugong Xu, Shunqing Zhang, Xiaoyun Wang, Shuangfeng Han",
        "IEEE IoTJ 12(11):17499–17513", 2025, ["物理队列", "双时间尺度", "PPO", "研究一", "研究二"],
        "Energy_Optimization_of_Multitask_DNN_Inference_in_MEC-Assisted_XR_Devices_A_Lyapunov-Guided_Reinforcement_Learning_Approach.pdf",
        "dynamic", "LyaPPO", lambda b: dynamic_entries(b, [(3, 5), (5, 6), (4, 5), (6, 9), (10, 11), (8, 12)]),
        "从本地计算、上传、边缘计算三段物理队列开始，检查不同计量单位和前后段到达耦合，再理解慢切点与快资源分配。")

    add("mad2rl", "DNN Partitioning, Task Offloading, and Resource Allocation in Dynamic Vehicular Networks: A Lyapunov-Guided Diffusion-Based Reinforcement Learning Approach", "MAD2RL",
        "Zhang Liu, Hongyang Du, Junzhe Lin, Zhibin Gao, Lianfen Huang, Seyyedali Hosseinalipour, Dusit Niyato",
        "IEEE TMC 24(3):1945–1962", 2025, ["车辆移动", "QMIX", "扩散策略", "物理队列", "研究一", "研究二"],
        "DNN_Partitioning_Task_Offloading_and_Resource_Allocation_in_Dynamic_Vehicular_Networks_A_Lyapunov-Guided_Diffusion-Based_Reinforcement_Learning_Approach.pdf",
        "dynamic", "MAD2RL", lambda b: dynamic_entries(b, [(4, 6), (7, 7), (5, 8), (8, 13), (15, 16), (8, 16)]),
        "先画CV、RSU、SV三个计算位置的队列，再区分扩散QMIX离散决策和KKT连续资源优化。实验车辆移动不等于已经模拟高铁连续切换。")

    def mobile_entries(b, model_pages, method_pages, experiment_pages, critique_pages):
        problem_key = next(label for label in b if label.startswith("问题与"))
        method_key = next(label for label in b if label.startswith("核心方法"))
        exp1, exp2 = numbered_experiments(b["两个有条件的实验发现"])
        return [
            note("问题、观测与场景假设", model_pages, "concept", b[problem_key]),
            note("核心方法与公式直觉", method_pages, "method", b[method_key]),
            note("实验发现一：条件与数据口径", experiment_pages[0], "experiment", exp1),
            note("实验发现二：收益与退化边界", experiment_pages[1], "experiment", exp2),
            note("研究关联与证据边界", critique_pages, "critique", b["与研究一、二的关联和边界"]),
        ]

    add("robust-dnn", "Robust DNN Partitioning and Resource Allocation Under Uncertain Inference Time", "Robust DNN",
        "Zhaojun Nan, Yunchu Han, Sheng Zhou, Zhisheng Niu", "IEEE TMC 25(3):3680–3696", 2026,
        ["概率截止期", "推理不确定性", "PCCP", "研究一"],
        "Robust_DNN_Partitioning_and_Resource_Allocation_Under_Uncertain_Inference_Time.pdf", "mobile", "Robust DNN",
        lambda b: mobile_entries(b, (3, 6), (6, 10), [(14, 14), (13, 13)], (8, 16)),
        "本篇以能耗为目标，以概率截止期为约束。优先辨认随机推理时间、确定上传时间与均值/方差安全裕量的条件，避免把概率保障读成逐任务绝不超时。")

    add("5g-lte-hsr", "The First 5G-LTE Comparative Study in Extreme Mobility", "5G-LTE 高铁实测",
        "Yueyang Pan, Ruihan Li, Chenren Xu", "ACM POMACS 6(1), Article 20", 2022,
        ["高铁实测", "5G/LTE", "切换", "上下行边界", "研究二"], "5glte.pdf", "mobile", "5G-LTE实测",
        lambda b: mobile_entries(b, (2, 4), (8, 17), [(4, 5), (12, 14)], (18, 20)),
        "这是一篇2021年高铁部署的跨层测量研究，不是带宽预测器。阅读吞吐数字之前先确认线路、时间、接入模式、协议实现和上下行方向。")

    add("dts-bwpredictor", "DTS-BWpredictor: Dual-scale temporal strategy based bandwidth prediction in highly dynamic links", "DTS-BWpredictor",
        "Difeng Zhu, Yafei Zhang, Xuan Gong, Hai-miao Hu, Yi Gao", "Computer Networks 259:111071", 2025,
        ["带宽预测", "双尺度", "BiLSTM", "反馈修正", "研究二"], "1-s2.0-S1389128625000398-main.pdf", "mobile", "DTS-BWpredictor",
        lambda b: mobile_entries(b, (3, 6), (3, 4), [(7, 7), (7, 7)], (6, 10)),
        "长时间依赖由A-BiLSTM学习，短时变化由拥塞反馈修正。本文实测输入是带宽、丢包和抖动，没有把GPS或速度作为现成模型输入。")

    def game_entries(b, problem, variables, formula, method, experiment, critique, formula_label="两个公式的直觉", method_label="方法"):
        problem_label = next(label for label in b if label.startswith("问题与"))
        return [
            note("问题与场景假设", problem, "concept", b[problem_label]),
            note("变量、目标与公平对象", variables, "concept", b["变量与目标"]),
            note("核心公式与直觉", formula, "concept", b[formula_label]),
            note("算法流程与保证", method, "method", b[method_label]),
            note("两项有出处的实验发现", experiment, "experiment", b["两项实验发现"]),
            note("研究二关联与适用边界", critique, "critique", b["研究二关联与边界"]),
        ]

    add("chen-offloading", "Efficient Multi-User Computation Offloading for Mobile-Edge Cloud Computing", "Chen 多用户卸载",
        "Xu Chen, Lei Jiao, Wenzhong Li, Xiaoming Fu", "IEEE/ACM ToN 24(5):2795–2808", 2016,
        ["势博弈", "有限改进", "多信道", "研究二"],
        "Efficient_Multi-User_Computation_Offloading_for_Mobile-Edge_Cloud_Computing.pdf", "game", "Chen",
        lambda b: game_entries(b, (2, 4), (3, 5), (3, 6), (7, 10), (12, 12), (2, 13)),
        "先弄清谁在自利决策，再看同信道干扰如何耦合成本。有限改进依赖异步单方严格改进；均衡不自动代表公平或集中最优。")

    add("hsr-potential-game", "Potential Game Based Task Offloading in the High-Speed Railway With Reinforcement Learning", "高铁 Potential Game",
        "Wei Wu, Haifeng Song, Hongwei Wang, Hairong Dong", "IEEE TITS 24(11):12671–12685", 2023,
        ["高铁卸载", "随机网络演算", "势博弈", "MADDPG", "研究二"],
        "Potential_Game_Based_Task_Offloading_in_the_High-Speed_Railway_With_Reinforcement_Learning.pdf", "game", "Wu",
        lambda b: game_entries(b, (3, 7), (7, 8), (4, 7), (8, 10), (12, 12), (7, 13), method_label="方法与保证"),
        "用随机网络演算与计算时长模型，把链路和算力竞争变为按期完成概率，再看最佳响应如何缩小PG-MADDPG动作集合。势博弈论证和学习曲线是不同证据。")

    def hml_entries(b):
        result = game_entries(b, (3, 4), (4, 5), (6, 7), (7, 8), (11, 14), (5, 14), formula_label="核心结构", method_label="元学习另做什么")
        result[3]["title"] = "元学习：与GNN结构分别解决什么"
        return result

    add("hml-gnn", "Hybrid-Task Meta-Learning: A GNN Approach for Scalable and Transferable Bandwidth Allocation", "HML-GNN",
        "Xin Hao, Changyang She, Phee Lep Yeoh, Yuhong Liu, Branka Vucetic, Yonghui Li", "IEEE TWC 23(12):19820–19835", 2024,
        ["带宽分配", "GNN", "元学习", "准入与QoS", "研究二"],
        "Hybrid-Task_Meta-Learning_A_GNN_Approach_for_Scalable_and_Transferable_Bandwidth_Allocation.pdf", "game", "Hao", hml_entries,
        "GNN的用户参数共享解决变用户数的结构兼容，HML改善跨场景适应。先看最低带宽需求与用户准入，再看Softmax读出如何保持预算和已入选用户的QoS。")

    if len(papers) != 11 or len({p["id"] for p in papers}) != 11:
        raise ValueError("Expected exactly 11 unique papers")
    if sum(p["page_count"] for p in papers) != 184:
        raise ValueError("Unexpected PDF page total")
    for paper in papers:
        allowed = range(9, 12) if paper["id"] == "qdmp" else range(6, 10)
        if len(paper["notes"]) not in allowed:
            raise ValueError(f"Unexpected note count: {paper['id']}")
    return papers


def main() -> None:
    papers = build()
    output = PROJECT / "data" / "seed.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(papers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sample = {
        "schema_version": 1,
        "notes": [
            note("研究问题（待填写模板）", (1, 1), "guide",
                 "这是一条通用占位模板，不是当前论文的解读。请依据原文填写，并将关联页码改为实际 PDF 文件页码。\n\n"
                 "### 研究问题\n\n- 研究对象：待填写。\n- 核心问题：待填写。\n- 系统假设：待填写。\n"
                 "- 决策变量：待填写。\n- 优化目标与约束：待填写。\n- 原文证据：待填写章节、公式或图表编号。"),
            dict(note("公式排版（非论文结论）", (1, 1), "concept",
                      "以下仅为数学排版示例，不代表任何论文的模型或结论。\n\n"
                      "行内公式：$y = ax + b$。\n\n独立公式：\n\n$$\nS = \\sum_{i=1}^{n} x_i\n$$\n\n"
                      "实际解析中，请说明符号、单位、假设，以及公式是原式、等价改写还是教学简化。"), sort_order=1),
        ],
    }
    examples = PROJECT / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    (examples / "解析导入示例.json").write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = "# 通用解析导入模板\n\n"
    for item in sample["notes"]:
        page_label = str(item["page_start"]) if item["page_start"] == item["page_end"] else f"{item['page_start']}-{item['page_end']}"
        metadata = json.dumps({key: item[key] for key in ("kind", "sort_order", "completed")}, separators=(",", ":"))
        md += f"## [p. {page_label}] {item['title']}\n<!-- paper-reader-note: {metadata} -->\n\n{item['content']}\n\n"
    (examples / "解析导入示例.md").write_text(md.rstrip() + "\n", encoding="utf-8")
    summary = {"papers": len(papers), "pages": sum(p["page_count"] for p in papers), "notes": sum(len(p["notes"]) for p in papers), "per_paper": {p["id"]: len(p["notes"]) for p in papers}}
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
