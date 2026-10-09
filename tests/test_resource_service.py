# tests/test_resource_service.py
"""
Test resource_service — không mock: catalog + ráp URL là logic thuần tất định.

Hợp đồng quan trọng nhất: KHÔNG BAO GIỜ trả link do LLM sinh — mọi URL hoặc
nằm trong catalog biên soạn tay, hoặc do backend tự ráp (search).
"""
from app.models.schemas import (
    ImprovementSuggestion,
    LLMAnalysis,
    LLMSuggestion,
    Priority,
)
from app.services.resource_service import enrich_response, tim_links


def test_skill_trong_catalog_tra_link_bien_soan():
    links = tim_links("Kubernetes")

    assert links, "Skill pho bien phai co link"
    assert all(link.url.startswith("https://") for link in links)
    assert all(link.kind != "search" for link in links)  # có catalog thì không fallback
    assert any("kubernetes.io" in link.url for link in links)


def test_skill_ghep_khop_nhieu_key_va_loc_chuoi_con():
    # "PostgreSQL hoặc MySQL" khớp key "postgresql", "mysql" VÀ "sql" —
    # "sql" là chuỗi con của 2 key kia nên phải bị loại (không trộn link SQLBolt
    # chung chung vào khi đã có link PostgreSQL cụ thể).
    links = tim_links("PostgreSQL hoặc MySQL")

    assert len(links) <= 3  # cap tối đa
    assert any("postgresql.org" in link.url for link in links)
    assert not any("sqlbolt.com" in link.url for link in links)


def test_github_actions_khong_keo_nham_link_git():
    # "CI/CD (GitHub Actions)" khớp "ci/cd", "github actions" và "git" —
    # "git" ⊂ "github actions" nên bị loại.
    links = tim_links("CI/CD (GitHub Actions)")

    assert any("docs.github.com" in link.url for link in links)
    assert not any("git-scm.com" in link.url for link in links)


def test_skill_la_fallback_link_tim_kiem_tu_rap():
    links = tim_links("Chứng chỉ kế toán trưởng")

    assert len(links) == 1
    assert links[0].kind == "search"
    # URL do TA ráp bằng quote_plus — khoảng trắng thành dấu +, không thể "bịa".
    assert links[0].url.startswith("https://www.google.com/search?q=")
    assert "+" in links[0].url


def test_enrich_response_gan_dung_cho():
    llm = LLMAnalysis(
        same_field=True,
        overall_score=75, skills_score=70, experience_score=70, education_score=90,
        summary="Kha phu hop.",
        suggestions=[
            LLMSuggestion(priority=Priority.HIGH, title="Hoc Docker", detail="...", related_skill="Docker"),
            LLMSuggestion(priority=Priority.LOW, title="Viet CV ro hon", detail="...", related_skill=None),
        ],
    )

    resp = enrich_response(llm.to_response(cv_id="cv1", jd_title=None))

    # Suggestion có related_skill -> được gắn link từ catalog.
    assert any("docs.docker.com" in link.url for link in resp.suggestions[0].resources)
    # Không có related_skill -> KHÔNG đoán mò, giữ rỗng.
    assert resp.suggestions[1].resources == []


def test_resources_serialize_camel_case():
    s = ImprovementSuggestion(
        priority=Priority.HIGH, title="t", detail="d", related_skill="Docker",
    )
    s.resources = tim_links("Docker")

    data = s.model_dump(by_alias=True, mode="json")
    assert {"title", "url", "kind"} <= data["resources"][0].keys()
    assert data["resources"][0]["kind"] in {"docs", "roadmap", "course", "search"}
