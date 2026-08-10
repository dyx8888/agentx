import json  # 加载评估数据集 JSON 文件
import math  # log2 用于 NDCG 计算
from pathlib import Path  # 跨平台文件路径处理，定位默认评估数据集

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger

try:  # ragas 是可选依赖，评估 RAG 生成质量
    from ragas import evaluate  # ragas 评估框架
    from ragas.metrics import faithfulness, answer_relevancy, context_recall  # 三个核心指标
    RAGAS_AVAILABLE = True  # 标记可用
except ImportError:  # ragas 未安装
    RAGAS_AVAILABLE = False  # 标记不可用
    logger.info("ragas_not_installed_generation_metrics_unavailable")  # 一次性提示


class RAGEvaluator:  # RAG 检索与生成质量评估器
    """RAG 检索与生成质量评估器"""  # 量化评估是持续优化的基础

    def __init__(self, eval_dataset_path: str = None):  # 可选自定义评估数据集路径
        self.eval_dataset_path = eval_dataset_path  # 数据集路径，None 时使用默认路径

    def hit_rate_at_k(self, query_results: list[list[str]], relevant_docs: list[list[str]], k: int = 5) -> float:  # Hit Rate@k：top-k 中是否包含相关文档
        if not query_results or not relevant_docs:  # 空数据检查
            return 0.0
        hits = 0  # 命中计数
        for results, relevant in zip(query_results, relevant_docs):  # 逐查询比对
            top_k = set(results[:k])  # 取 top-k 结果
            if top_k & set(relevant):  # 交集非空即命中
                hits += 1
        return hits / len(query_results) if query_results else 0.0  # 命中率

    def mrr(self, query_results: list[list[str]], relevant_docs: list[list[str]]) -> float:  # MRR：平均倒数排名
        if not query_results or not relevant_docs:  # 空数据检查
            return 0.0
        reciprocal_ranks = []  # 每个查询的倒数排名
        for results, relevant in zip(query_results, relevant_docs):  # 逐查询计算
            for i, doc in enumerate(results, 1):  # 从 1 开始排名
                if doc in relevant:  # 找到第一个相关文档即停止
                    reciprocal_ranks.append(1.0 / i)  # 1/排名
                    break
            else:  # 没找到相关文档
                reciprocal_ranks.append(0.0)  # 0 分
        return sum(reciprocal_ranks) / len(reciprocal_ranks)  # 平均倒数排名

    def ndcg_at_k(self, query_results: list[list[str]], relevance_scores: list[dict[str, int]], k: int = 10) -> float:  # NDCG@k：归一化折损累计增益
        if not query_results or not relevance_scores:  # 空数据检查
            return 0.0
        ndcg_values = []  # 每个查询的 NDCG
        for results, scores in zip(query_results, relevance_scores):  # 逐查询计算
            dcg = 0.0  # DCG：折损累计增益
            for i, doc in enumerate(results[:k], 1):  # 遍历 top-k
                rel = scores.get(doc, 0)  # 相关性分数
                dcg += (2 ** rel - 1) / math.log2(i + 1)  # 折损因子 = 1/log2(rank+1)

            ideal = sorted(scores.values(), reverse=True)[:k]  # 理想排序（按相关性降序）
            idcg = 0.0  # IDCG：理想 DCG
            for i, rel in enumerate(ideal, 1):  # 计算理想 DCG
                idcg += (2 ** rel - 1) / math.log2(i + 1)

            ndcg_values.append(dcg / idcg if idcg > 0 else 0.0)  # NDCG = DCG/IDCG，除零保护
        return sum(ndcg_values) / len(ndcg_values) if ndcg_values else 0.0  # 平均 NDCG

    def evaluate_faithfulness(self, questions: list[str], contexts: list[str], answers: list[str]) -> dict:  # 忠实度评估：回答是否基于上下文
        if not RAGAS_AVAILABLE:  # ragas 不可用
            logger.warning("ragas_unavailable_skipping_faithfulness")  # 跳过
            return {"faithfulness": None, "warning": "ragas not installed"}  # 返回空结果
        try:  # ragas 评估可能失败
            from ragas import SingleTurnSample  # 单轮评估样本
            from ragas.metrics import Faithfulness  # 忠实度指标
            scorer = Faithfulness()  # 创建评分器
            scores = []  # 收集分数
            for q, ctx, ans in zip(questions, contexts, answers):  # 逐样本评估
                sample = SingleTurnSample(user_input=q, retrieved_contexts=[ctx], response=ans)  # 构建样本
                score = scorer.single_turn_score(sample)  # 评分
                scores.append(score)
            return {"faithfulness": sum(scores) / len(scores) if scores else 0.0}  # 平均忠实度
        except Exception as e:  # 评估失败
            logger.warning("faithfulness_eval_failed", error=str(e))  # 记录错误
            return {"faithfulness": None, "error": str(e)}  # 返回错误信息

    def evaluate_answer_relevancy(self, questions: list[str], answers: list[str]) -> dict:  # 答案相关性评估：回答是否与问题相关
        if not RAGAS_AVAILABLE:  # ragas 不可用
            logger.warning("ragas_unavailable_skipping_relevancy")  # 跳过
            return {"answer_relevancy": None, "warning": "ragas not installed"}  # 返回空结果
        try:  # ragas 评估可能失败
            from ragas import SingleTurnSample  # 单轮评估样本
            from ragas.metrics import AnswerRelevancy  # 答案相关性指标
            scorer = AnswerRelevancy()  # 创建评分器
            scores = []  # 收集分数
            for q, ans in zip(questions, answers):  # 逐样本评估
                sample = SingleTurnSample(user_input=q, response=ans)  # 构建样本
                score = scorer.single_turn_score(sample)  # 评分
                scores.append(score)
            return {"answer_relevancy": sum(scores) / len(scores) if scores else 0.0}  # 平均相关性
        except Exception as e:  # 评估失败
            logger.warning("relevancy_eval_failed", error=str(e))  # 记录错误
            return {"answer_relevancy": None, "error": str(e)}  # 返回错误信息

    def load_dataset(self) -> list[dict]:  # 加载评估数据集
        path = self.eval_dataset_path  # 用户指定路径
        if not path:  # 未指定时使用默认路径
            path = Path(__file__).parent.parent.parent / "tests" / "rag_eval_dataset.json"  # 相对于 rag_evaluator.py 向上三级到项目根目录
        try:  # 文件可能存在
            with open(path, "r", encoding="utf-8") as f:  # UTF-8 编码
                return json.load(f)  # 加载 JSON 数据集
        except Exception as e:  # 文件不存在或格式错误
            logger.warning("eval_dataset_load_failed", error=str(e), path=str(path))  # 记录错误
            return []  # 返回空列表

    def run_full_evaluation(self) -> dict:  # 运行完整评估
        dataset = self.load_dataset()  # 加载数据集
        if not dataset:  # 无数据集
            return {"status": "error", "message": "No evaluation dataset available"}  # 返回错误

        queries = [d["query"] for d in dataset]  # 提取所有查询
        relevant_docs = [d.get("relevant_docs", []) for d in dataset]  # 提取相关文档
        query_results = [d.get("retrieved_docs", []) for d in dataset]  # 提取检索结果
        relevance_scores = [d.get("relevance_scores", {}) for d in dataset]  # 提取相关性分数

        report = {  # 构建评估报告
            "status": "ok",  # 评估状态
            "dataset_size": len(dataset),  # 数据集大小
            "retrieval_metrics": {  # 检索指标
                "hit_rate@5": self.hit_rate_at_k(query_results, relevant_docs, k=5),  # Hit Rate@5
                "hit_rate@10": self.hit_rate_at_k(query_results, relevant_docs, k=10),  # Hit Rate@10
                "mrr": self.mrr(query_results, relevant_docs),  # MRR
                "ndcg@10": self.ndcg_at_k(query_results, relevance_scores, k=10),  # NDCG@10
            },
        }

        if RAGAS_AVAILABLE and all(d.get("answer") and d.get("context") for d in dataset):  # 有生成结果时才评估生成指标
            questions = [d["query"] for d in dataset]  # 提取问题
            contexts = [d.get("context", "") for d in dataset]  # 提取上下文
            answers = [d.get("answer", "") for d in dataset]  # 提取答案
            report["generation_metrics"] = {  # 生成指标
                **self.evaluate_faithfulness(questions, contexts, answers),  # 忠实度
                **self.evaluate_answer_relevancy(questions, answers),  # 答案相关性
            }

        return report  # 返回完整评估报告