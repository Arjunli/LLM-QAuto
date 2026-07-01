"""
核心数据模型 - 完全通用，不绑定任何特定领域
"""

from typing import Any, Dict, List, Optional, Union
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field


class TestStatus(str, Enum):
    """测试状态"""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    PARTIAL = "partial"  # 部分通过


class TestInput(BaseModel):
    """测试输入 - 通用结构"""
    id: str = Field(..., description="唯一标识")
    prompt: str = Field(..., description="主输入内容")
    variables: Dict[str, Any] = Field(default_factory=dict, description="变量值")
    context: Dict[str, Any] = Field(default_factory=dict, description="上下文信息")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class MediaAsset(BaseModel):
    """单张图片或多模态产物"""
    id: str = ""
    source: str = "response"  # response | reference | upload
    remote_url: Optional[str] = None
    local_path: Optional[str] = None
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    size_bytes: Optional[int] = None
    error: Optional[str] = None


class TestOutput(BaseModel):
    """测试输出 - 通用结构（文本 / 图像 / 混合）"""
    content: str = Field(default="", description="文本输出或 JSON 摘要")
    content_mode: str = Field(
        default="text",
        description="text | image | mixed — 由引擎根据 parser 与产物自动判定",
    )
    media: List[MediaAsset] = Field(default_factory=list, description="图像等二进制产物")
    raw_response: Optional[Dict] = Field(default=None, description="原始响应")
    latency_ms: float = Field(default=0.0, description="响应延迟(ms)")
    tokens_used: Optional[int] = Field(default=None, description="token使用量")
    model_version: Optional[str] = Field(default=None, description="模型版本")
    timestamp: datetime = Field(default_factory=datetime.now)
    error: Optional[str] = Field(default=None, description="错误信息")


class DimensionResult(BaseModel):
    """单个维度的评判结果"""
    dimension_id: str
    evaluator_type: str
    passed: bool
    score: float = Field(ge=0, le=10)
    categories: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    evidence: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    judgment_time_ms: float = 0.0


class TestCase(BaseModel):
    """单个测试用例（输入+输出+评判结果）"""
    id: str
    input: TestInput
    output: TestOutput
    dimension_results: Dict[str, List[DimensionResult]] = Field(default_factory=dict)
    aggregated_score: float = 0.0
    passed: bool = True
    failed_dimensions: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CategoryStats(BaseModel):
    """类别统计"""
    category: str
    count: int
    percentage: float
    confidence_interval: tuple = Field(default=(0, 0))  # (lower, upper)


class DimensionStats(BaseModel):
    """维度统计"""
    dimension_id: str
    dimension_name: str = Field(
        default="",
        description="维度显示名称（报告展示用，缺省回退为 dimension_id）",
    )
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    avg_score: float
    min_score: float
    max_score: float
    std_score: float
    category_distribution: List[CategoryStats] = Field(default_factory=list)
    fail_reasons: Dict[str, int] = Field(default_factory=dict)  # 失败原因统计


class PassCriteriaResult(BaseModel):
    """通过标准检查结果"""
    criteria_id: str
    description: str
    passed: bool
    actual_value: Any
    expected_value: Any
    details: str


class ReportCaseRollup(BaseModel):
    """单条用例在 JSON 报告中的摘要（避免整份 raw/http body 塞进 report）"""

    case_id: str
    passed: bool = True
    aggregated_score: float = 0.0
    input_prompt: str = ""
    input_variables: Dict[str, Any] = Field(default_factory=dict)
    invoke_latency_ms: float = 0.0
    output_error: Optional[str] = None
    content_mode: str = "text"
    output_char_count: int = 0
    output_preview: str = ""
    media_count: int = 0
    media_preview_paths: List[str] = Field(
        default_factory=list,
        description="相对 artifacts 目录的图片路径，供 HTML 报告展示",
    )
    judgment_latency_ms_total: float = 0.0
    failed_dimensions: List[str] = Field(default_factory=list)
    dimensions: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="维度 id -> 该维度评判链末尾一条结果的摘要（见 engine 拼装）",
    )
    output_parser_keys: List[str] = Field(
        default_factory=list,
        description="output_parser.keys 配置的解析字段名",
    )
    parsed_fields: Dict[str, Any] = Field(
        default_factory=dict,
        description="从被测接口解析后的各字段值（便于与评委对照）",
    )
    judge_excerpt: str = Field(
        default="",
        description="实际提交评委的 Listing 摘录（JSON 文本）",
    )
    invoke_raw_preview: str = Field(
        default="",
        description="被测接口原始响应摘要（HTTP body）",
    )


class TestReport(BaseModel):
    """测试报告"""
    # 元信息
    run_id: str
    project_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: TestStatus
    
    # 统计
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    total_cost_usd: float = 0.0
    
    # 维度统计
    dimension_stats: List[DimensionStats] = Field(default_factory=list)
    
    # 门禁检查
    criteria_results: List[PassCriteriaResult] = Field(default_factory=list)

    # 套件元信息与聚合策略（便于报告自描述）
    suite_meta: Dict[str, Any] = Field(default_factory=dict)
    aggregation_method: str = "weighted_average"

    # 每条用例摘要（成功/失败均包含；大段正文仅存 preview）
    cases: List[ReportCaseRollup] = Field(default_factory=list)

    # 失败案例（保留代表性样本）
    failed_examples: List[TestCase] = Field(default_factory=list)
    
    # 争议样本
    disputed_cases: List[TestCase] = Field(default_factory=list)
    
    # 汇总
    summary: str = ""
    recommendations: List[str] = Field(default_factory=list)
    
    """早于批量调用即中止时标记原因（如接口不可达），用于跳过 HTML 等完整报告"""
    abort_reason: Optional[str] = None

    # 原始数据位置
    artifacts_path: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return self.model_dump()


class ConnectorConfig(BaseModel):
    """连接器配置"""
    name: str
    config: Dict[str, Any] = Field(default_factory=dict)


class InputFormatterConfig(BaseModel):
    """输入格式化配置"""
    name: str
    template: Union[str, Dict] = Field(default="")


class MediaParserConfig(BaseModel):
    """从 JSON 响应中提取图像产物"""
    urls_path: Optional[str] = None
    url_path: Optional[str] = None
    b64_path: Optional[str] = None
    images_path: Optional[str] = None
    download: bool = True
    max_images: int = 8
    timeout: float = 90.0


class OutputParserConfig(BaseModel):
    """输出解析配置"""
    name: str
    path: Optional[str] = None  # JSON path表达式（相对解析后的接口 body）
    keys: Optional[List[str]] = None  # 若给定，仅从 path 所指对象中取这些字段（缺的为 null）；可显著缩短评委输入
    content_mode: str = "auto"  # auto | text | image | mixed
    media: Optional[MediaParserConfig] = None
    custom_script: Optional[str] = None


class TargetConfig(BaseModel):
    """被测对象配置"""
    type: str = "api"
    connector: ConnectorConfig
    input_formatter: InputFormatterConfig
    output_parser: OutputParserConfig


class VariableConfig(BaseModel):
    """变量配置"""
    name: str
    type: str = "enum"  # enum | file | random_select | range
    values: Optional[List[Any]] = None
    path: Optional[str] = None
    pool: Optional[List[Any]] = None
    count: Optional[int] = None
    min: Optional[float] = None
    max: Optional[float] = None


class SamplingConfig(BaseModel):
    """采样配置"""
    total: Optional[int] = None
    method: str = "uniform"
    deduplicate: bool = True
    seed: Optional[int] = None


class DataGeneratorConfig(BaseModel):
    """数据生成器配置"""
    strategy: str = "template_cartesian"
    variables: List[VariableConfig] = Field(default_factory=list)
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    prompt_template: str = ""
    rows: List[Dict[str, Any]] = Field(default_factory=list)


class RuleConfig(BaseModel):
    """规则配置"""
    name: str
    condition: str
    params: Dict[str, Any] = Field(default_factory=dict)
    severity: str = "error"  # error | warning


class RuleEvaluatorConfig(BaseModel):
    """规则评判器配置"""
    type: str = "rule"
    name: str
    rules: List[RuleConfig]


class LLMEvaluatorConfig(BaseModel):
    """LLM评判器配置"""
    type: str = "llm"
    name: str
    model: str
    prompt_template: str
    output_schema: Dict[str, str] = Field(default_factory=dict)
    context: Dict[str, str] = Field(default_factory=dict)
    temperature: float = 0.1
    max_tokens: int = 2000


class EmbeddingEvaluatorConfig(BaseModel):
    """向量相似度评判器配置"""
    type: str = "embedding"
    name: str
    model: str = "text-embedding-3-small"
    reference_pool: str  # 参考样本文件路径
    similarity_threshold: float = 0.8


class ReferenceEvaluatorConfig(BaseModel):
    """参考对比评判器配置"""
    type: str = "reference"
    name: str
    reference_file: str
    method: str = "exact"  # exact | semantic | regex


EvaluatorConfigType = Union[
    RuleEvaluatorConfig,
    LLMEvaluatorConfig,
    EmbeddingEvaluatorConfig,
    ReferenceEvaluatorConfig
]


class DimensionConfig(BaseModel):
    """评判维度配置"""
    id: str
    name: str
    description: str = ""
    weight: float = 1.0
    fail_fast: bool = False
    evaluators: List[Dict[str, Any]] = Field(default_factory=list)


class CategoryDistributionTarget(BaseModel):
    """类别分布目标"""
    category: str
    min_percent: Optional[float] = None
    max_percent: Optional[float] = None
    fail_if_exceed: bool = False


class DimensionPassCriteria(BaseModel):
    """维度通过标准"""
    id: str
    min_avg_score: Optional[float] = None
    max_fail_rate: Optional[float] = None
    category_distribution: List[CategoryDistributionTarget] = Field(default_factory=list)


class GlobalPassCriteria(BaseModel):
    """全局通过标准"""
    min_total_score: Optional[float] = None
    min_dimension_coverage: float = 0.8


class StatisticalCriteria(BaseModel):
    """统计标准"""
    confidence_level: float = 0.95
    min_sample_size: int = 30


class PassCriteriaConfig(BaseModel):
    """通过标准配置"""
    global_criteria: GlobalPassCriteria = Field(default_factory=GlobalPassCriteria)
    dimensions: List[DimensionPassCriteria] = Field(default_factory=list)
    statistical: StatisticalCriteria = Field(default_factory=StatisticalCriteria)


class EvaluationConfig(BaseModel):
    """评判配置"""
    dimensions: List[DimensionConfig] = Field(default_factory=list)
    aggregation_method: str = "weighted_average"
    # 单次全评：一次 LLM 调用返回多维度分数（见 evaluator type=llm_batch）
    batch_llm: Optional[Dict[str, Any]] = None


class TestSuiteConfig(BaseModel):
    """测试套件完整配置"""
    meta: Dict[str, Any] = Field(default_factory=dict)
    target: TargetConfig
    data_generator: DataGeneratorConfig
    evaluation: EvaluationConfig
    pass_criteria: PassCriteriaConfig
