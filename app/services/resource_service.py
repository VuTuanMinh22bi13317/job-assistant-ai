# app/services/resource_service.py
"""
Catalog tài nguyên học tập — trả lời "học Ở ĐÂU" cho từng suggestion.

Nguyên tắc (nối dài triết lý A+B): LLM chỉ sinh DỮ KIỆN ("thiếu Kubernetes",
related_skill="Kubernetes"); URL là thứ TẤT ĐỊNH do backend sở hữu:
- Có trong catalog biên soạn tay -> link uy tín (docs chính thức, roadmap.sh,
  nguồn học miễn phí, ưu tiên bản tiếng Việt nếu có).
- Không có -> tự RÁP link tìm kiếm (kind="search") — không bao giờ chết link.
LLM không bao giờ sinh URL (bịa URL là bệnh kinh điển, không grounding được).
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote_plus

from app.models.schemas import AnalysisResponse, ResourceLink

# ==========================================================================
# CATALOG — key là chuỗi ĐÃ normalize, match theo chứa-chuỗi với tên skill
# (nên "AWS (EC2, S3, Lambda)" khớp key "aws"). Mỗi key tối đa 2 link.
# Chỉ đưa URL ỔN ĐỊNH lâu dài (trang docs gốc, không deep-link dễ gãy).
# ==========================================================================
_CATALOG: dict[str, list[ResourceLink]] = {
    # --- Backend / ngôn ngữ ---
    "python": [
        ResourceLink(title="Python Tutorial — docs chính thức", url="https://docs.python.org/3/tutorial/", kind="docs"),
        ResourceLink(title="Lộ trình học Python (roadmap.sh)", url="https://roadmap.sh/python", kind="roadmap"),
    ],
    "fastapi": [
        ResourceLink(title="FastAPI — docs chính thức (học qua ví dụ)", url="https://fastapi.tiangolo.com/", kind="docs"),
    ],
    "django": [
        ResourceLink(title="Django — docs chính thức", url="https://docs.djangoproject.com/", kind="docs"),
    ],
    "postgresql": [
        ResourceLink(title="PostgreSQL — docs chính thức", url="https://www.postgresql.org/docs/", kind="docs"),
        ResourceLink(title="PostgreSQL Tutorial", url="https://www.postgresqltutorial.com/", kind="course"),
    ],
    "mysql": [
        ResourceLink(title="MySQL — docs chính thức", url="https://dev.mysql.com/doc/", kind="docs"),
    ],
    "sql": [
        ResourceLink(title="SQLBolt — học SQL tương tác", url="https://sqlbolt.com/", kind="course"),
        ResourceLink(title="Lộ trình SQL (roadmap.sh)", url="https://roadmap.sh/sql", kind="roadmap"),
    ],
    "redis": [
        ResourceLink(title="Redis — docs chính thức", url="https://redis.io/docs/", kind="docs"),
    ],
    # --- DevOps / hạ tầng ---
    "docker": [
        ResourceLink(title="Docker Get Started — docs chính thức", url="https://docs.docker.com/get-started/", kind="docs"),
        ResourceLink(title="Lộ trình Docker (roadmap.sh)", url="https://roadmap.sh/docker", kind="roadmap"),
    ],
    "kubernetes": [
        ResourceLink(title="Kubernetes Tutorials — docs chính thức", url="https://kubernetes.io/docs/tutorials/", kind="docs"),
        ResourceLink(title="Lộ trình Kubernetes (roadmap.sh)", url="https://roadmap.sh/kubernetes", kind="roadmap"),
    ],
    "aws": [
        ResourceLink(title="AWS Getting Started", url="https://aws.amazon.com/getting-started/", kind="docs"),
        ResourceLink(title="AWS Skill Builder — khóa học miễn phí", url="https://skillbuilder.aws/", kind="course"),
    ],
    "terraform": [
        ResourceLink(title="Terraform Tutorials — HashiCorp", url="https://developer.hashicorp.com/terraform/tutorials", kind="docs"),
    ],
    "kafka": [
        ResourceLink(title="Apache Kafka — docs chính thức", url="https://kafka.apache.org/documentation/", kind="docs"),
        ResourceLink(title="Confluent Developer — học Kafka miễn phí", url="https://developer.confluent.io/", kind="course"),
    ],
    "rabbitmq": [
        ResourceLink(title="RabbitMQ Tutorials", url="https://www.rabbitmq.com/tutorials", kind="docs"),
    ],
    "ci/cd": [
        ResourceLink(title="GitHub Actions — docs chính thức", url="https://docs.github.com/actions", kind="docs"),
        ResourceLink(title="Lộ trình DevOps (roadmap.sh)", url="https://roadmap.sh/devops", kind="roadmap"),
    ],
    "github actions": [
        ResourceLink(title="GitHub Actions — docs chính thức", url="https://docs.github.com/actions", kind="docs"),
    ],
    "jenkins": [
        ResourceLink(title="Jenkins — docs chính thức", url="https://www.jenkins.io/doc/", kind="docs"),
    ],
    "git": [
        ResourceLink(title="Pro Git (có bản tiếng Việt)", url="https://git-scm.com/book/vi/v2", kind="docs"),
        ResourceLink(title="Learn Git Branching — học tương tác (có tiếng Việt)", url="https://learngitbranching.js.org/?locale=vi_VN", kind="course"),
    ],
    # --- Testing ---
    "unit test": [
        ResourceLink(title="pytest — docs chính thức", url="https://docs.pytest.org/", kind="docs"),
    ],
    "pytest": [
        ResourceLink(title="pytest — docs chính thức", url="https://docs.pytest.org/", kind="docs"),
    ],
    "selenium": [
        ResourceLink(title="Selenium — docs chính thức", url="https://www.selenium.dev/documentation/", kind="docs"),
    ],
    # --- Frontend ---
    "react": [
        ResourceLink(title="React — docs chính thức (react.dev/learn)", url="https://react.dev/learn", kind="docs"),
        ResourceLink(title="F8 (fullstack.edu.vn) — khóa JS/React tiếng Việt miễn phí", url="https://fullstack.edu.vn/", kind="course"),
    ],
    "typescript": [
        ResourceLink(title="TypeScript Handbook — docs chính thức", url="https://www.typescriptlang.org/docs/handbook/", kind="docs"),
    ],
    "next.js": [
        ResourceLink(title="Next.js Learn — khóa chính thức", url="https://nextjs.org/learn", kind="course"),
    ],
    # --- Data ---
    "spark": [
        ResourceLink(title="Apache Spark — docs chính thức", url="https://spark.apache.org/docs/latest/", kind="docs"),
    ],
    "airflow": [
        ResourceLink(title="Apache Airflow — docs chính thức", url="https://airflow.apache.org/docs/", kind="docs"),
    ],
    "dbt": [
        ResourceLink(title="dbt — docs chính thức", url="https://docs.getdbt.com/", kind="docs"),
    ],
    "power bi": [
        ResourceLink(title="Power BI — Microsoft Learn", url="https://learn.microsoft.com/power-bi/", kind="docs"),
    ],
    "excel": [
        ResourceLink(title="Trợ giúp Excel — Microsoft", url="https://support.microsoft.com/excel", kind="docs"),
    ],
    # --- Kiến trúc / senior ---
    "system design": [
        ResourceLink(title="System Design Primer (GitHub)", url="https://github.com/donnemartin/system-design-primer", kind="docs"),
        ResourceLink(title="Lộ trình System Design (roadmap.sh)", url="https://roadmap.sh/system-design", kind="roadmap"),
    ],
    "hệ thống phân tán": [
        ResourceLink(title="System Design Primer (GitHub)", url="https://github.com/donnemartin/system-design-primer", kind="docs"),
    ],
    # --- Marketing ---
    "seo": [
        ResourceLink(title="Google Search Central — docs chính thức", url="https://developers.google.com/search/docs", kind="docs"),
        ResourceLink(title="Moz — Beginner's Guide to SEO", url="https://moz.com/beginners-guide-to-seo", kind="course"),
    ],
    "google ads": [
        ResourceLink(title="Google Skillshop — khóa chính thức miễn phí", url="https://skillshop.withgoogle.com/", kind="course"),
    ],
    "google analytics": [
        ResourceLink(title="Google Skillshop — khóa chính thức miễn phí", url="https://skillshop.withgoogle.com/", kind="course"),
    ],
    "ga4": [
        ResourceLink(title="Google Skillshop — khóa chính thức miễn phí", url="https://skillshop.withgoogle.com/", kind="course"),
    ],
    "facebook ads": [
        ResourceLink(title="Meta Blueprint — khóa chính thức", url="https://www.facebook.com/business/learn", kind="course"),
    ],
    # --- Mobile / Design (đợt mở rộng đa ngành) ---
    "react native": [
        ResourceLink(title="React Native — docs chính thức", url="https://reactnative.dev/docs/getting-started", kind="docs"),
    ],
    "figma": [
        ResourceLink(title="Figma Help Center — học Figma chính thức", url="https://help.figma.com/", kind="docs"),
    ],
    "ui/ux": [
        ResourceLink(title="Nielsen Norman Group — bài viết UX nền tảng", url="https://www.nngroup.com/articles/", kind="docs"),
        ResourceLink(title="Google UX Design (Coursera)", url="https://www.coursera.org/professional-certificates/google-ux-design", kind="course"),
    ],
    "user research": [
        ResourceLink(title="Nielsen Norman Group — bài viết UX nền tảng", url="https://www.nngroup.com/articles/", kind="docs"),
    ],
    # --- Văn phòng / CSKH / Sales / HR (ngoài IT) ---
    "crm": [
        ResourceLink(title="HubSpot Academy — khóa CRM/Sales/Service miễn phí", url="https://academy.hubspot.com/", kind="course"),
    ],
    "hubspot": [
        ResourceLink(title="HubSpot Academy — khóa miễn phí chính thức", url="https://academy.hubspot.com/", kind="course"),
    ],
    "zendesk": [
        ResourceLink(title="Zendesk Help — tài liệu chính thức", url="https://support.zendesk.com/", kind="docs"),
    ],
    "chăm sóc khách hàng": [
        ResourceLink(title="HubSpot Academy — khóa Customer Service miễn phí", url="https://academy.hubspot.com/", kind="course"),
    ],
    "customer service": [
        ResourceLink(title="HubSpot Academy — khóa Customer Service miễn phí", url="https://academy.hubspot.com/", kind="course"),
    ],
    "bán hàng": [
        ResourceLink(title="HubSpot Academy — khóa Sales miễn phí", url="https://academy.hubspot.com/", kind="course"),
    ],
    "tin học văn phòng": [
        ResourceLink(title="Trợ giúp Microsoft Office", url="https://support.microsoft.com/office", kind="docs"),
    ],
    "jira": [
        ResourceLink(title="Jira Guides — Atlassian chính thức", url="https://www.atlassian.com/software/jira/guides", kind="docs"),
    ],
    "tableau": [
        ResourceLink(title="Tableau Training — khóa chính thức", url="https://www.tableau.com/learn/training", kind="course"),
    ],
}


def _normalize(text: str) -> str:
    """NFKC + lowercase + gộp khoảng trắng — cùng chuẩn với eval/keyword_hit."""
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def tim_links(skill: str, toi_da: int = 3) -> list[ResourceLink]:
    """
    Tìm link cho một skill. Không bao giờ trả rỗng:
    1. Match catalog theo chứa-chuỗi (key nằm trong tên skill đã normalize).
    2. Key là CHUỖI CON của key khác cùng khớp thì bỏ (vd skill "PostgreSQL"
       khớp cả "postgresql" lẫn "sql" -> chỉ giữ "postgresql"; "GitHub Actions"
       khớp cả "github actions" lẫn "git" -> bỏ "git").
    3. Không khớp gì -> 1 link tìm kiếm tự ráp (kind="search").
    """
    chuoi = _normalize(skill)

    khop = [key for key in _CATALOG if key in chuoi]
    # Luật chuỗi-con: giữ key cụ thể nhất trong số các key cùng khớp.
    khop = [k for k in khop if not any(k != kh and k in kh for kh in khop)]

    links: list[ResourceLink] = []
    da_co: set[str] = set()  # dedupe theo url (nhiều key có thể chung link)
    for key in khop:
        for link in _CATALOG[key]:
            if link.url not in da_co:
                da_co.add(link.url)
                links.append(link)

    if not links:
        # Fallback tất định: URL do TA ráp từ tên skill -> không thể "bịa".
        links = [
            ResourceLink(
                title=f'Tìm tài liệu học "{skill}"',
                url=f"https://www.google.com/search?q={quote_plus(f'học {skill} cơ bản')}",
                kind="search",
            )
        ]
    return links[:toi_da]


def enrich_response(resp: AnalysisResponse) -> AnalysisResponse:
    """
    Gắn resources vào từng suggestion có related_skill — bước làm giàu TẤT ĐỊNH
    sau khi LLM trả kết quả (cùng họ với to_response gắn metadata/verdict/floor).
    Suggestion không có related_skill thì giữ resources = [] (không đoán mò).
    """
    for s in resp.suggestions:
        if s.related_skill:
            s.resources = tim_links(s.related_skill)
    return resp
