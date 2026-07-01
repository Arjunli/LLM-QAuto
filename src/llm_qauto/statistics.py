"""
统计工具 - 置信区间计算、假设检验等
"""

import math
from typing import Tuple, Optional


def wilson_score_interval(
    successes: int,
    total: int,
    confidence: float = 0.95
) -> Tuple[float, float]:
    """
    Wilson score interval - 用于二项分布比例的置信区间
    比正态近似更精确，尤其适用于小样本和极端比例
    
    Args:
        successes: 成功次数
        total: 总样本数
        confidence: 置信水平 (默认0.95)
    
    Returns:
        (lower_bound, upper_bound)
    """
    if total == 0:
        return (0.0, 1.0)
    
    if confidence == 0.95:
        z = 1.96
    elif confidence == 0.99:
        z = 2.576
    elif confidence == 0.90:
        z = 1.645
    else:
        # 从标准正态分布获取z值
        from scipy import stats
        z = stats.norm.ppf((1 + confidence) / 2)
    
    p = successes / total
    
    # Wilson interval formula
    denominator = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt(
        (p * (1 - p) + z**2 / (4 * total)) / total
    ) / denominator
    
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    
    return (lower, upper)


def compute_confidence_interval(
    values: list,
    confidence: float = 0.95
) -> Tuple[float, float, float]:
    """
    计算数值列表的置信区间（使用t分布）
    
    Returns:
        (mean, lower_bound, upper_bound)
    """
    import numpy as np
    from scipy import stats
    
    if not values:
        return (0.0, 0.0, 0.0)
    
    arr = np.array(values)
    mean = np.mean(arr)
    std = np.std(arr, ddof=1)  # 样本标准差
    n = len(arr)
    
    if n < 2:
        return (mean, mean, mean)
    
    # t分布
    t_value = stats.t.ppf((1 + confidence) / 2, df=n-1)
    margin = t_value * std / math.sqrt(n)
    
    return (mean, mean - margin, mean + margin)


def adaptive_sample_size(
    observed_p: float,
    target_margin: float = 0.05,
    confidence: float = 0.95
) -> int:
    """
    计算达到目标误差边际所需的最小样本量
    
    Args:
        observed_p: 观察到的比例
        target_margin: 目标误差边际
        confidence: 置信水平
    
    Returns:
        建议的样本量
    """
    if confidence == 0.95:
        z = 1.96
    elif confidence == 0.99:
        z = 2.576
    else:
        from scipy import stats
        z = stats.norm.ppf((1 + confidence) / 2)
    
    # 保守估计使用p=0.5（最大方差）
    p = 0.5
    
    n = (z**2 * p * (1 - p)) / (target_margin ** 2)
    
    return math.ceil(n)


def early_termination_check(
    current_successes: int,
    current_total: int,
    target_min: Optional[float],
    target_max: Optional[float],
    confidence: float = 0.95
) -> str:
    """
    提前终止检查 - 用于自适应抽样
    
    Returns:
        "continue": 继续抽样
        "pass_early": 已确定通过
        "fail_early": 已确定失败
    """
    if current_total < 30:  # 最小样本量
        return "continue"
    
    p = current_successes / current_total
    ci_lower, ci_upper = wilson_score_interval(current_successes, current_total, confidence)
    
    # 如果置信区间下限已超过上限阈值，确定失败
    if target_max is not None and ci_lower > target_max:
        return "fail_early"
    
    # 如果置信区间上限仍低于上限阈值，确定通过
    if target_max is not None and ci_upper < target_max:
        return "pass_early"
    
    # 如果置信区间下限已超过下限阈值，确定通过
    if target_min is not None and ci_lower > target_min:
        return "pass_early"
    
    # 如果置信区间上限仍低于下限阈值，确定失败
    if target_min is not None and ci_upper < target_min:
        return "fail_early"
    
    return "continue"


def cohens_d(group1: list, group2: list) -> float:
    """
    计算Cohen's d效应量 - 用于比较两组差异
    """
    import numpy as np
    
    mean1, mean2 = np.mean(group1), np.mean(group2)
    std1, std2 = np.std(group1, ddof=1), np.std(group2, ddof=1)
    
    n1, n2 = len(group1), len(group2)
    
    # 合并标准差
    pooled_std = math.sqrt(
        ((n1 - 1) * std1**2 + (n2 - 1) * std2**2) / (n1 + n2 - 2)
    )
    
    if pooled_std == 0:
        return 0.0
    
    return (mean1 - mean2) / pooled_std


def fleiss_kappa(ratings: list, n_categories: int) -> float:
    """
    Fleiss' Kappa - 多评判者一致性检验
    
    Args:
        ratings: list of list, 每个子list是一个样本的多个评判结果
        n_categories: 类别数
    
    Returns:
        kappa值
    """
    import numpy as np
    
    ratings = np.array(ratings)
    n_subjects, n_raters = ratings.shape
    
    # 计算每个类别的总评判次数
    n_total = n_subjects * n_raters
    
    # 计算每个类别的比例
    p = np.sum(ratings, axis=0) / n_total
    
    # 计算每个评判者的一致性
    P = np.sum(ratings * (ratings - 1), axis=1) / (n_raters * (n_raters - 1))
    P_mean = np.mean(P)
    
    # 期望一致性
    P_e = np.sum(p ** 2)
    
    if 1 - P_e == 0:
        return 1.0
    
    kappa = (P_mean - P_e) / (1 - P_e)
    
    return kappa
