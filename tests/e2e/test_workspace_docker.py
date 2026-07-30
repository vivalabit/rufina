from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

from playwright.sync_api import Page, expect, sync_playwright


OWNER_ID = "workspace-e2e-owner"
APPLICATION_ID = "application-workspace-e2e"
JOB_ID = "job-workspace-e2e"
CONSENT_VERSION = "e2e-consent-v1"
AI_BACKEND = "openclaw_codex"


def minimal_docx(paragraphs: list[str]) -> bytes:
    escaped = [
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for text in paragraphs
    ]
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
        for text in escaped
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/>'
        "</w:sectPr></w:body></w:document>"
    )
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
    relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document_relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""

    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", document_relationships)
        archive.writestr("word/styles.xml", styles)
    return output.getvalue()


def data_url(content: bytes) -> str:
    encoded = base64.b64encode(content).decode("ascii")
    return (
        "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;"
        f"base64,{encoded}"
    )


class WorkspaceDockerE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(os.environ["E2E_REPO_ROOT"])
        cls.api_url = os.environ["E2E_API_URL"]
        cls.web_url = os.environ["E2E_WEB_URL"]
        cls.compose_project = os.environ["E2E_COMPOSE_PROJECT"]
        cls.compose_files = [
            cls.repo_root / "compose.yaml",
            cls.repo_root / "tests/e2e/compose.e2e.yaml",
        ]
        cls.headers = {"X-Rufina-Owner-Id": OWNER_ID}
        cls.wait_for_api()

    @classmethod
    def tearDownClass(cls) -> None:
        # Keep explicit cleanup even though the runner removes the isolated Docker volumes.
        # This also protects personal data if the test is pointed at a persistent environment.
        for path in (f"/applications/{APPLICATION_ID}", f"/jobs/{JOB_ID}"):
            try:
                cls.api_request("DELETE", path, expected_status=204)
            except (AssertionError, OSError, URLError):
                pass

    @classmethod
    def compose(cls, *arguments: str, capture: bool = False) -> str:
        command = ["docker", "compose", "--project-name", cls.compose_project]
        for compose_file in cls.compose_files:
            command.extend(["--file", str(compose_file)])
        command.extend(arguments)
        result = subprocess.run(
            command,
            check=True,
            cwd=cls.repo_root,
            text=True,
            capture_output=capture,
        )
        return result.stdout.strip() if capture else ""

    @classmethod
    def wait_for_api(cls, timeout: float = 90) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urlopen(f"{cls.api_url}/health", timeout=2) as response:
                    if response.status == 200:
                        return
            except (OSError, URLError):
                time.sleep(1)
        raise AssertionError("Docker API did not become healthy")

    @classmethod
    def wait_for_postgres(cls, timeout: float = 60) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                cls.compose("exec", "-T", "postgres", "pg_isready", "-U", "tasko", "-d", "tasko")
                return
            except subprocess.CalledProcessError:
                time.sleep(1)
        raise AssertionError("Docker PostgreSQL did not become ready")

    @classmethod
    def api_request(
        cls,
        method: str,
        path: str,
        payload: object | None = None,
        expected_status: int = 200,
    ) -> object | None:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {**cls.headers, **({"Content-Type": "application/json"} if body else {})}
        request = Request(f"{cls.api_url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=180) as response:
                content = response.read()
                if response.status != expected_status:
                    raise AssertionError(f"{method} {path}: expected {expected_status}, got {response.status}")
                return json.loads(content) if content else None
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise AssertionError(
                f"{method} {path}: expected {expected_status}, got {error.code}: {detail}"
            ) from error

    @classmethod
    def seed_authoritative_match(cls, profile: dict[str, object], job: dict[str, object]) -> None:
        cls.api_request("PUT", "/profile", profile)
        cls.api_request("PUT", "/jobs", {"jobs": [{"id": JOB_ID, "data": job}]})
        cls.api_request(
            "PUT",
            "/privacy/ai-consent",
            {
                "version": CONSENT_VERSION,
                "backend": AI_BACKEND,
                "retentionDays": 7,
            },
        )
        cls.api_request(
            "POST",
            "/jobs/ai-match?force=true",
            {"jobs": [{"id": JOB_ID, "data": job}]},
        )
        documents = json.loads(str(profile["documents"]))
        resume = next(
            document
            for document in documents
            if document["category"] == "CV / Resume"
        )
        imported_resume = cls.api_request(
            "POST",
            "/profile/import-master-resume",
            {
                "resumeFileName": resume["file_name"],
                "resumeDataUrl": resume["data_url"],
            },
        )
        cls.api_request(
            "POST",
            "/profile/import-master-resume/confirm",
            {
                "sourceFileId": imported_resume["sourceFileId"],
                "masterResume": imported_resume["masterResume"],
                "confirmedSections": [
                    "contacts",
                    "summary",
                    "skills",
                    "experience",
                    "education",
                    "projects",
                    "certifications",
                ],
            },
        )
        cls.api_request("DELETE", "/privacy/ai-consent?deleteData=false", expected_status=204)
        cls.api_request("PUT", "/profile?allow_destructive=true", {})

    def legacy_fixture(self) -> tuple[dict[str, object], dict[str, object]]:
        uploaded_at = "2026-07-19T10:00:00.000Z"
        resume = data_url(
            minimal_docx(
                [
                    "Alex Morgan",
                    "Senior Product Designer",
                    "Product designer for complex B2B workflows.",
                    "Acme Design AG",
                    "Senior Product Designer · January 2022–Present",
                    "Led research and redesigned a production workflow.",
                    "Product design · User research · Prototyping",
                ]
            )
        )
        cover = data_url(
            minimal_docx(
                [
                    "Dear Hiring Team,",
                    "I am applying for the Senior Product Designer role.",
                    "My verified experience includes B2B workflow research and delivery.",
                    "Kind regards,",
                    "Alex Morgan",
                ]
            )
        )
        profile: dict[str, object] = {
            "name": "Alex Morgan",
            "current_role": "Product Designer",
            "desired_role": "Senior Product Designer",
            "location": "Zürich, Switzerland",
            "headline": "Product designer for complex B2B workflows",
            "skills": "Product design\nUser research\nPrototyping",
            "experience": "Led research and redesigned a production workflow for enterprise users.",
            "education": "BA Interaction Design",
            "documents": json.dumps(
                [
                    {
                        "id": "legacy-resume-source",
                        "title": "Lebenslauf Zürich",
                        "category": "CV / Resume",
                        "language": "English",
                        "file_name": "Lebenslauf-Zürich.docx",
                        "file_size": "2 KB",
                        "file_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "uploaded_at": uploaded_at,
                        "data_url": resume,
                    },
                    {
                        "id": "legacy-cover-source",
                        "title": "Anschreiben Müller",
                        "category": "Cover Letter",
                        "language": "English",
                        "file_name": "Anschreiben-Müller.docx",
                        "file_size": "2 KB",
                        "file_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "uploaded_at": uploaded_at,
                        "data_url": cover,
                    },
                ],
                ensure_ascii=False,
            ),
        }
        job: dict[str, object] = {
            "id": JOB_ID,
            "company": "Müller & Söhne",
            "title": "Senior Produktdesigner Zürich",
            "location": "Zürich, Switzerland",
            "type": "Full-time",
            "salary": "CHF 130,000",
            "posted": "Today",
            "experience": "5+ years",
            "department": "Product",
            "match": 92,
            "logo": "manual",
            "overview": "Lead research and delivery for a complex B2B platform.",
            "responsibilities": ["Lead discovery", "Ship production workflows"],
            "requirements": ["Product design", "User research"],
            "skills": ["Product design", "User research"],
            "salaryAverage": "CHF 130,000",
            "salaryMin": "CHF 120,000",
            "salaryMax": "CHF 140,000",
            "recommendations": [],
            "companyInfo": "Enterprise software company",
            "reviews": [],
            "similarJobs": [],
            "applyUrl": "https://example.com/jobs/product-designer",
            "sourceUrl": "https://example.com/jobs/product-designer",
            "addedAt": uploaded_at,
        }
        return profile, job

    def assert_downloaded_docx(
        self,
        page: Page,
        card_title: str,
        expected_text: str,
    ) -> str:
        card = page.get_by_role("heading", name=card_title).locator("xpath=ancestor::article[1]")
        with page.expect_download(timeout=60_000) as download_info:
            card.get_by_role("link", name="DOCX", exact=True).first.click()
        download = download_info.value
        destination = Path(tempfile.mkdtemp()) / download.suggested_filename
        download.save_as(destination)
        self.assertTrue(zipfile.is_zipfile(destination), destination)
        with zipfile.ZipFile(destination) as archive:
            self.assertIn("word/document.xml", archive.namelist())
            document_xml = archive.read("word/document.xml").decode()
        self.assertIn(expected_text, document_xml)
        return download.suggested_filename

    def test_workspace_generation_survives_outage_retry_and_container_restart(self) -> None:
        profile, job = self.legacy_fixture()
        self.seed_authoritative_match(profile, job)
        legacy_application = {
            "id": APPLICATION_ID,
            "status": "draft",
            "appliedAt": "2026-07-19",
            "nextStep": "Prepare application pack",
            "notes": "Migrated from legacy browser storage",
            "documents": [],
            "job": job,
        }
        fixture = {"profile": profile, "applications": [legacy_application]}

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                accept_downloads=True,
                extra_http_headers=self.headers,
            )
            context.add_init_script(
                script=f"""
                (() => {{
                  if (location.origin !== {json.dumps(self.web_url)} || sessionStorage.getItem('tasko-e2e-seeded')) return;
                  const fixture = {json.dumps(fixture, ensure_ascii=False)};
                  localStorage.clear();
                  localStorage.setItem('tasko.profile.v1', JSON.stringify(fixture.profile));
                  localStorage.setItem('tasko.applications.v1', JSON.stringify(fixture.applications));
                  sessionStorage.setItem('tasko-e2e-seeded', '1');
                }})();
                """
            )
            page = context.new_page()
            page.on("dialog", lambda dialog: dialog.accept())
            page.set_default_timeout(30_000)
            page.goto(
                f"{self.web_url}/#application-workspace/{APPLICATION_ID}",
                wait_until="domcontentloaded",
            )

            expect(page.get_by_text("Services available")).to_be_visible(timeout=30_000)
            expect(
                page.get_by_role("heading", name="Senior Produktdesigner Zürich")
            ).to_be_visible(timeout=30_000)
            page.get_by_role("button").filter(has_text="Confirm details").click()
            expect(page.get_by_text("Which production workflow did you lead?")).to_be_visible(
                timeout=30_000
            )

            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                applications = self.api_request("GET", "/applications")
                migrated_profile = self.api_request("GET", "/profile")
                if applications and migrated_profile["name"] == "Alex Morgan":
                    break
                time.sleep(0.5)
            else:
                self.fail("Legacy profile/application data did not migrate to PostgreSQL")

            self.compose("stop", "api")
            page.reload(wait_until="domcontentloaded")
            expect(page.get_by_text("Services unavailable")).to_be_visible(timeout=30_000)

            self.compose("start", "api")
            self.wait_for_api()
            page.get_by_role("button", name="Retry", exact=True).first.click()
            expect(page.get_by_text("Services available")).to_be_visible(timeout=30_000)
            page.get_by_role("button").filter(has_text="Confirm details").click()
            expect(page.get_by_text("Which production workflow did you lead?")).to_be_visible()

            yes_buttons = page.get_by_role("button", name="yes", exact=True)
            for index in range(3):
                yes_buttons.nth(index).click()
            examples = page.get_by_placeholder("Add a true, concrete example")
            examples.nth(0).fill(
                "Led research and delivery for the verified enterprise workflow redesign."
            )
            examples.nth(1).fill(
                "Reduced the number of steps enterprise users needed to finish the workflow."
            )
            examples.nth(2).fill(
                "The role combines complex product discovery with measurable workflow improvement."
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                saved_confirmations = self.api_request(
                    "GET",
                    f"/applications/{APPLICATION_ID}/confirmations",
                )
                if len(saved_confirmations) == 3 and all(
                    item["response"] == "yes" and item["exampleText"]
                    for item in saved_confirmations
                ):
                    break
                time.sleep(0.5)
            else:
                self.fail("Candidate confirmations were not saved")

            page.get_by_role("button").filter(has_text="Create documents").click()
            generate_cv = page.get_by_role("button", name="Generate Tailored CV")
            expect(generate_cv).to_be_enabled(timeout=30_000)
            generate_cv.click()
            expect(page.get_by_role("dialog", name="Your application context will be sent to OpenAI")).to_be_visible()
            page.get_by_role("spinbutton", name="Keep AI results for (days)").fill("7")
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="Continue to AI").click()
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                documents = self.api_request(
                    "GET",
                    f"/documents?applicationId={APPLICATION_ID}",
                )
                resume_document = next(
                    (
                        document
                        for document in documents
                        if document["type"] == "tailored_resume"
                    ),
                    None,
                )
                if resume_document:
                    resume_version = next(
                        version
                        for version in resume_document["versions"]
                        if version["version"] == resume_document["currentVersion"]
                    )
                    if (
                        resume_version["hasRenderedArtifact"]
                        and resume_version["artifact"]["sourceAtsFinalReviewId"]
                    ):
                        break
                time.sleep(0.5)
            else:
                self.fail("Tailored resume PDF was not rendered and attached")
            expect(page.get_by_text("Unvalidated · v1")).to_be_visible(timeout=30_000)

            generate_cover = page.get_by_role("button", name="Generate Cover letter")
            expect(generate_cover).to_be_enabled(timeout=30_000)
            generate_cover.click()
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                documents = self.api_request(
                    "GET",
                    f"/documents?applicationId={APPLICATION_ID}",
                )
                cover_document = next(
                    (
                        document
                        for document in documents
                        if document["type"] == "cover_letter"
                    ),
                    None,
                )
                if cover_document:
                    cover_version = next(
                        version
                        for version in cover_document["versions"]
                        if version["version"] == cover_document["currentVersion"]
                    )
                    if cover_version["hasRenderedDocx"]:
                        break
                time.sleep(0.5)
            else:
                self.fail("Cover letter DOCX was not generated")
            expect(page.get_by_text("Unvalidated · v1")).to_have_count(2, timeout=30_000)

            page.get_by_role("button", name="Generate application pack").click()
            expect(page.get_by_text("Application PDF and cover letter are ready")).to_be_visible(
                timeout=240_000
            )
            expect(page.get_by_text("Unvalidated · v2")).to_be_visible(timeout=30_000)

            privacy = self.api_request("GET", "/privacy/ai-consent")
            self.assertTrue(privacy["hasCurrentConsent"])
            self.assertEqual(privacy["currentBackend"], AI_BACKEND)
            self.assertEqual(privacy["retentionDays"], 7)
            confirmations = self.api_request(
                "GET", f"/applications/{APPLICATION_ID}/confirmations"
            )
            self.assertEqual(
                {item["questionId"] for item in confirmations},
                {"production-workflow", "workflow-outcome", "product-motivation"},
            )

            documents = self.api_request("GET", f"/documents?applicationId={APPLICATION_ID}")
            self.assertEqual(len(documents), 2)
            for document in documents:
                current = next(
                    version
                    for version in document["versions"]
                    if version["version"] == document["currentVersion"]
                )
                if document["type"] == "tailored_resume":
                    self.assertEqual(document["currentVersion"], 1)
                    self.assertTrue(current["hasRenderedArtifact"])
                    self.assertTrue(current["artifact"]["sourceAtsFinalReviewId"])
                    self.assertEqual(
                        document["inputVersions"]["generationMode"],
                        "recruiter_xyz_ats",
                    )
                    for stage_id in (
                        "seniorRecruiterAnalysisId",
                        "experienceRewriteId",
                        "atsFinalReviewId",
                    ):
                        self.assertTrue(document["inputVersions"][stage_id])
                else:
                    self.assertEqual(document["currentVersion"], 2)
                    self.assertTrue(current["hasRenderedDocx"])
                    self.assertEqual(current["factualValidation"], {})
                    self.assertEqual(current["visualValidation"], {})

            cv_filename = self.assert_downloaded_docx(page, "Tailored CV", "Zürich")
            cover_filename = self.assert_downloaded_docx(page, "Cover letter", "Müller")
            self.assertTrue(cv_filename.endswith(".docx"))
            self.assertTrue(cover_filename.endswith(".docx"))

            self.compose("restart", "postgres")
            self.wait_for_postgres()
            self.compose("restart", "api")
            self.wait_for_api()
            page.reload(wait_until="domcontentloaded")
            expect(page.get_by_text("Services available")).to_be_visible(timeout=30_000)
            expect(page.get_by_text("Unvalidated · v1")).to_be_visible(timeout=60_000)
            expect(page.get_by_text("Unvalidated · v2")).to_be_visible(timeout=60_000)
            self.assert_downloaded_docx(page, "Tailored CV", "Zürich")

            browser.close()


if __name__ == "__main__":
    unittest.main()
