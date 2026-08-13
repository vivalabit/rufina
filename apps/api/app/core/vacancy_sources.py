from dataclasses import dataclass

AGGREGATOR_SOURCE_IDS = ("linkedin", "indeed", "jobs_ch")


@dataclass(frozen=True)
class DirectCompanyParserDefinition:
    """Declarative registration for one official company career-page parser."""

    id: str
    name: str
    careers_url: str
    parser_path: str
    settings_map: tuple[tuple[str, str], ...] = ()
    full_catalog: bool = True


# Keep company-specific imports out of the central search runner. Adding a company
# only requires its parser module and one lightweight catalog registration here.
DIRECT_COMPANY_PARSERS = (
    DirectCompanyParserDefinition(
        id="sbb",
        name="SBB CFF FFS",
        careers_url=(
            "https://company.sbb.ch/de/jobs-karriere/jobs/offene-stellen.html?startItem=1"
        ),
        parser_path="app.services.parsers.companies.sbb:SbbJobsParser",
        settings_map=(
            ("base_url", "sbb_jobs_base_url"),
            ("timeout_seconds", "sbb_jobs_timeout_seconds"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="swisscom",
        name="Swisscom",
        careers_url=(
            "https://swisscom.wd103.myworkdayjobs.com/en-US/"
            "SwisscomExternalCareers"
        ),
        parser_path=(
            "app.services.parsers.companies.swisscom:SwisscomJobsParser"
        ),
        settings_map=(
            ("base_url", "swisscom_jobs_base_url"),
            ("timeout_seconds", "swisscom_jobs_timeout_seconds"),
            ("max_pages", "swisscom_jobs_max_pages"),
            ("detail_workers", "swisscom_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="galaxus",
        name="Galaxus",
        careers_url="https://jobs.migros.ch/de/unsere-unternehmen/galaxus/",
        parser_path="app.services.parsers.companies.galaxus:GalaxusJobsParser",
        settings_map=(
            ("base_url", "galaxus_jobs_base_url"),
            ("timeout_seconds", "galaxus_jobs_timeout_seconds"),
            ("detail_workers", "galaxus_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="migros_bank",
        name="Migros Bank",
        careers_url=(
            "https://jobs.migros.ch/de/unsere-unternehmen/"
            "migros-bank/offene-stellen"
        ),
        parser_path=(
            "app.services.parsers.companies.migros_bank:MigrosBankJobsParser"
        ),
        settings_map=(
            ("base_url", "migros_bank_jobs_base_url"),
            ("timeout_seconds", "migros_bank_jobs_timeout_seconds"),
            ("detail_workers", "migros_bank_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="die_post",
        name="Die Post",
        careers_url="https://job.post.ch/search?locale=en_US",
        parser_path="app.services.parsers.companies.die_post:DiePostJobsParser",
        settings_map=(
            ("base_url", "die_post_jobs_base_url"),
            ("timeout_seconds", "die_post_jobs_timeout_seconds"),
            ("max_pages", "die_post_jobs_max_pages"),
            ("max_catalog_passes", "die_post_jobs_max_catalog_passes"),
            ("detail_workers", "die_post_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="raiffeisen",
        name="Raiffeisen",
        careers_url="https://jobs.raiffeisen.ch/",
        parser_path=(
            "app.services.parsers.companies.raiffeisen:RaiffeisenJobsParser"
        ),
        settings_map=(
            ("base_url", "raiffeisen_jobs_base_url"),
            ("api_url", "raiffeisen_jobs_api_url"),
            ("timeout_seconds", "raiffeisen_jobs_timeout_seconds"),
            ("max_pages", "raiffeisen_jobs_max_pages"),
            ("max_catalog_passes", "raiffeisen_jobs_max_catalog_passes"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bundesverwaltung",
        name="Bundesverwaltung",
        careers_url=(
            "https://jobs.admin.ch/?lang=de&f=verwaltungseinheit:36497"
            "&intranet=1"
        ),
        parser_path=(
            "app.services.parsers.companies.bundesverwaltung:"
            "BundesverwaltungJobsParser"
        ),
        settings_map=(
            ("base_url", "bundesverwaltung_jobs_base_url"),
            ("api_url", "bundesverwaltung_jobs_api_url"),
            ("timeout_seconds", "bundesverwaltung_jobs_timeout_seconds"),
            ("max_pages", "bundesverwaltung_jobs_max_pages"),
            (
                "max_catalog_passes",
                "bundesverwaltung_jobs_max_catalog_passes",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="axa_schweiz",
        name="AXA Schweiz",
        careers_url=(
            "https://careers.axa.com/careers-home/jobs?"
            "country=Switzerland&page=1"
        ),
        parser_path=(
            "app.services.parsers.companies.axa_schweiz:AxaSchweizJobsParser"
        ),
        settings_map=(
            ("base_url", "axa_schweiz_jobs_base_url"),
            ("api_url", "axa_schweiz_jobs_api_url"),
            ("timeout_seconds", "axa_schweiz_jobs_timeout_seconds"),
            ("max_pages", "axa_schweiz_jobs_max_pages"),
            (
                "max_catalog_passes",
                "axa_schweiz_jobs_max_catalog_passes",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="sunrise",
        name="Sunrise",
        careers_url="https://careers.sunrise.ch/gb/en/search-results",
        parser_path="app.services.parsers.companies.sunrise:SunriseJobsParser",
        settings_map=(
            ("base_url", "sunrise_jobs_base_url"),
            ("timeout_seconds", "sunrise_jobs_timeout_seconds"),
            ("max_pages", "sunrise_jobs_max_pages"),
            (
                "max_catalog_passes",
                "sunrise_jobs_max_catalog_passes",
            ),
            ("detail_workers", "sunrise_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="iss",
        name="ISS Schweiz",
        careers_url=(
            "https://www.ch.issworld.com/de-ch/karriere/offene-stellen"
        ),
        parser_path="app.services.parsers.companies.iss:IssJobsParser",
        settings_map=(
            ("base_url", "iss_jobs_base_url"),
            ("api_url", "iss_jobs_api_url"),
            ("timeout_seconds", "iss_jobs_timeout_seconds"),
            ("detail_workers", "iss_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="accenture",
        name="Accenture",
        careers_url="https://www.accenture.com/ch-en/careers/jobsearch",
        parser_path=(
            "app.services.parsers.companies.accenture:AccentureJobsParser"
        ),
        settings_map=(
            ("base_url", "accenture_jobs_base_url"),
            ("api_url", "accenture_jobs_api_url"),
            ("timeout_seconds", "accenture_jobs_timeout_seconds"),
            ("max_pages", "accenture_jobs_max_pages"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="csem",
        name="CSEM",
        careers_url="https://www.csem.ch/en/jobs/",
        parser_path="app.services.parsers.companies.csem:CsemJobsParser",
        settings_map=(
            ("base_url", "csem_jobs_base_url"),
            ("timeout_seconds", "csem_jobs_timeout_seconds"),
            ("detail_workers", "csem_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="deloitte",
        name="Deloitte",
        careers_url="https://apply.deloitte.ch/CHCareers/",
        parser_path="app.services.parsers.companies.deloitte:DeloitteJobsParser",
        settings_map=(
            ("base_url", "deloitte_jobs_base_url"),
            ("timeout_seconds", "deloitte_jobs_timeout_seconds"),
            ("max_pages", "deloitte_jobs_max_pages"),
            ("max_catalog_passes", "deloitte_jobs_max_catalog_passes"),
            ("detail_workers", "deloitte_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="zuercher_kantonalbank",
        name="Zürcher Kantonalbank",
        careers_url="https://apply.refline.ch/792841/search.html",
        parser_path=(
            "app.services.parsers.companies.zuercher_kantonalbank:"
            "ZuercherKantonalbankJobsParser"
        ),
        settings_map=(
            ("base_url", "zuercher_kantonalbank_jobs_base_url"),
            ("timeout_seconds", "zuercher_kantonalbank_jobs_timeout_seconds"),
            ("detail_workers", "zuercher_kantonalbank_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="flughafen_zuerich",
        name="Flughafen Zürich",
        careers_url=(
            "https://www.flughafen-zuerich.ch/de/unternehmen/jobs/karriere/"
            "stellenangebote"
        ),
        parser_path=(
            "app.services.parsers.companies.flughafen_zuerich:"
            "FlughafenZuerichJobsParser"
        ),
        settings_map=(
            ("base_url", "flughafen_zuerich_jobs_base_url"),
            ("api_url", "flughafen_zuerich_jobs_api_url"),
            ("api_key", "flughafen_zuerich_jobs_api_key"),
            ("timeout_seconds", "flughafen_zuerich_jobs_timeout_seconds"),
            ("detail_workers", "flughafen_zuerich_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ubs_students_graduates",
        name="UBS Students & Graduates",
        careers_url=(
            "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?"
            "partnerid=25008&siteid=5131&PageType=searchResults&"
            "SearchType=linkquery&LinkID=15232"
            "#keyWordSearch=&locationSearch=Switzerland"
        ),
        parser_path=(
            "app.services.parsers.companies.ubs_students_graduates:"
            "UbsStudentsGraduatesJobsParser"
        ),
        settings_map=(
            ("base_url", "ubs_students_graduates_jobs_base_url"),
            ("api_url", "ubs_students_graduates_jobs_api_url"),
            ("timeout_seconds", "ubs_students_graduates_jobs_timeout_seconds"),
            ("max_pages", "ubs_students_graduates_jobs_max_pages"),
            ("detail_workers", "ubs_students_graduates_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="abb_switzerland",
        name="ABB Schweiz",
        careers_url=(
            "https://careers.abb/global/en/search-results?"
            "rk=l-abb-switzerland-careers&sortBy=Most%20relevant"
        ),
        parser_path=(
            "app.services.parsers.companies.abb_switzerland:"
            "AbbSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "abb_switzerland_jobs_base_url"),
            ("timeout_seconds", "abb_switzerland_jobs_timeout_seconds"),
            ("max_pages", "abb_switzerland_jobs_max_pages"),
            ("max_catalog_passes", "abb_switzerland_jobs_max_catalog_passes"),
            ("page_workers", "abb_switzerland_jobs_page_workers"),
            ("detail_workers", "abb_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="huawei_switzerland",
        name="Huawei Switzerland",
        careers_url="https://careers.huaweirc.ch/jobs",
        parser_path=(
            "app.services.parsers.companies.huawei_switzerland:"
            "HuaweiSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "huawei_switzerland_jobs_base_url"),
            ("timeout_seconds", "huawei_switzerland_jobs_timeout_seconds"),
            ("detail_workers", "huawei_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bdo_switzerland",
        name="BDO Switzerland",
        careers_url="https://www.bdo.ch/en-gb/careers/open-jobs",
        parser_path=(
            "app.services.parsers.companies.bdo_switzerland:"
            "BdoSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "bdo_switzerland_jobs_base_url"),
            ("api_url", "bdo_switzerland_jobs_api_url"),
            ("timeout_seconds", "bdo_switzerland_jobs_timeout_seconds"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="endress_hauser_switzerland",
        name="Endress+Hauser Switzerland",
        careers_url=(
            "https://careers.endress.com/Switzerland/content/search/?"
            "locale=en_US&currentPage=1&pageSize=20&"
            "addresses%2Fcountry=Switzerland&orderBy=datePosted&isDesc=true"
        ),
        parser_path=(
            "app.services.parsers.companies.endress_hauser_switzerland:"
            "EndressHauserSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "endress_hauser_switzerland_jobs_base_url"),
            ("api_url", "endress_hauser_switzerland_jobs_api_url"),
            ("customer_id", "endress_hauser_switzerland_jobs_customer_id"),
            ("api_key", "endress_hauser_switzerland_jobs_api_key"),
            (
                "timeout_seconds",
                "endress_hauser_switzerland_jobs_timeout_seconds",
            ),
            ("max_pages", "endress_hauser_switzerland_jobs_max_pages"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="microsoft_switzerland",
        name="Microsoft Switzerland",
        careers_url=(
            "https://apply.careers.microsoft.com/careers?start=0&"
            "location=Switzerland%2C+Z%C3%BCrich%2C+Z%C3%BCrich&"
            "pid=1970393556942270&sort_by=distance&filter_distance=160&"
            "filter_include_remote=1&filter_include_relocation=0"
        ),
        parser_path=(
            "app.services.parsers.companies.microsoft_switzerland:"
            "MicrosoftSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "microsoft_switzerland_jobs_base_url"),
            ("api_url", "microsoft_switzerland_jobs_api_url"),
            ("detail_api_url", "microsoft_switzerland_jobs_detail_api_url"),
            ("timeout_seconds", "microsoft_switzerland_jobs_timeout_seconds"),
            ("max_pages", "microsoft_switzerland_jobs_max_pages"),
            ("detail_workers", "microsoft_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="sap_switzerland",
        name="SAP Switzerland",
        careers_url="https://jobs.sap.com/go/SAP-Jobs-in-Switzerland/915101/",
        parser_path=(
            "app.services.parsers.companies.sap_switzerland:"
            "SapSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "sap_switzerland_jobs_base_url"),
            ("timeout_seconds", "sap_switzerland_jobs_timeout_seconds"),
            ("max_pages", "sap_switzerland_jobs_max_pages"),
            ("max_catalog_passes", "sap_switzerland_jobs_max_catalog_passes"),
            ("detail_workers", "sap_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="s_peers",
        name="s-peers",
        careers_url="https://s-peers.com/karriere-jobs/stellenausschreibungen/",
        parser_path="app.services.parsers.companies.s_peers:SPeersJobsParser",
        settings_map=(
            ("base_url", "s_peers_jobs_base_url"),
            ("timeout_seconds", "s_peers_jobs_timeout_seconds"),
            ("detail_workers", "s_peers_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="mobiliar",
        name="Mobiliar",
        careers_url="https://jobs.mobiliar.ch/go/Jobs/506974/",
        parser_path="app.services.parsers.companies.mobiliar:MobiliarJobsParser",
        settings_map=(
            ("base_url", "mobiliar_jobs_base_url"),
            ("api_url", "mobiliar_jobs_api_url"),
            ("timeout_seconds", "mobiliar_jobs_timeout_seconds"),
            ("max_pages", "mobiliar_jobs_max_pages"),
            ("max_catalog_passes", "mobiliar_jobs_max_catalog_passes"),
            ("detail_workers", "mobiliar_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="emmi",
        name="Emmi",
        careers_url=(
            "https://group.emmi.com/che/de/arbeiten-bei-emmi/offene-stellen"
        ),
        parser_path="app.services.parsers.companies.emmi:EmmiJobsParser",
        settings_map=(
            ("base_url", "emmi_jobs_base_url"),
            ("api_url", "emmi_jobs_api_url"),
            ("timeout_seconds", "emmi_jobs_timeout_seconds"),
            ("max_pages", "emmi_jobs_max_pages"),
            ("max_catalog_passes", "emmi_jobs_max_catalog_passes"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="sulzer_switzerland",
        name="Sulzer Switzerland",
        careers_url=(
            "https://sulzer.wd502.myworkdayjobs.com/SulzerJobs?"
            "locationcountry=187134fccb084a0ea9b4b95f23890dbe"
        ),
        parser_path=(
            "app.services.parsers.companies.sulzer_switzerland:"
            "SulzerSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "sulzer_switzerland_jobs_base_url"),
            ("timeout_seconds", "sulzer_switzerland_jobs_timeout_seconds"),
            ("max_pages", "sulzer_switzerland_jobs_max_pages"),
            ("detail_workers", "sulzer_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="siegfried",
        name="Siegfried",
        careers_url="https://siegfried.wd103.myworkdayjobs.com/external",
        parser_path=(
            "app.services.parsers.companies.siegfried:SiegfriedJobsParser"
        ),
        settings_map=(
            ("base_url", "siegfried_jobs_base_url"),
            ("timeout_seconds", "siegfried_jobs_timeout_seconds"),
            ("max_pages", "siegfried_jobs_max_pages"),
            ("max_catalog_passes", "siegfried_jobs_max_catalog_passes"),
            ("detail_workers", "siegfried_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="switch",
        name="Switch",
        careers_url=(
            "https://recruitingapp-2563.umantis.com/Jobs/1?lang=ger"
        ),
        parser_path="app.services.parsers.companies.switch:SwitchJobsParser",
        settings_map=(
            ("base_url", "switch_jobs_base_url"),
            ("timeout_seconds", "switch_jobs_timeout_seconds"),
            ("max_pages", "switch_jobs_max_pages"),
            ("detail_workers", "switch_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="huber_suhner_switzerland",
        name="Huber+Suhner Switzerland",
        careers_url="https://recruiting.hubersuhner.com/Jobs/All",
        parser_path=(
            "app.services.parsers.companies.huber_suhner_switzerland:"
            "HuberSuhnerSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "huber_suhner_switzerland_jobs_base_url"),
            ("timeout_seconds", "huber_suhner_switzerland_jobs_timeout_seconds"),
            ("max_pages", "huber_suhner_switzerland_jobs_max_pages"),
            ("detail_workers", "huber_suhner_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="stadler_it_switzerland",
        name="Stadler IT Switzerland",
        careers_url=(
            "https://www.stadlerrail.com/de/karriere/offene-stellen"
            "?10=1077445&25=1098730&"
        ),
        parser_path=(
            "app.services.parsers.companies.stadler_it_switzerland:"
            "StadlerItSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "stadler_it_switzerland_jobs_base_url"),
            ("catalog_url", "stadler_it_switzerland_jobs_catalog_url"),
            ("timeout_seconds", "stadler_it_switzerland_jobs_timeout_seconds"),
            ("max_pages", "stadler_it_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "stadler_it_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "stadler_it_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ebp_switzerland",
        name="EBP Switzerland",
        careers_url=(
            "https://www.ebp.global/ch-de/karriere/offene-stellen/stellenangebote"
        ),
        parser_path=(
            "app.services.parsers.companies.ebp_switzerland:"
            "EbpSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "ebp_switzerland_jobs_base_url"),
            ("catalog_url", "ebp_switzerland_jobs_catalog_url"),
            ("timeout_seconds", "ebp_switzerland_jobs_timeout_seconds"),
            ("detail_workers", "ebp_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ruag_switzerland",
        name="RUAG Switzerland",
        careers_url="https://www.ruag.ch/en/working-us/job-portal",
        parser_path=(
            "app.services.parsers.companies.ruag_switzerland:"
            "RuagSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "ruag_switzerland_jobs_base_url"),
            ("timeout_seconds", "ruag_switzerland_jobs_timeout_seconds"),
            ("max_pages", "ruag_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "ruag_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "ruag_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="cyberlink",
        name="Cyberlink",
        careers_url="https://www.cyberlink.ch/de/cyberlink/jobs",
        parser_path=(
            "app.services.parsers.companies.cyberlink:CyberlinkJobsParser"
        ),
        settings_map=(
            ("base_url", "cyberlink_jobs_base_url"),
            ("catalog_url", "cyberlink_jobs_catalog_url"),
            ("timeout_seconds", "cyberlink_jobs_timeout_seconds"),
            ("detail_workers", "cyberlink_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ergon",
        name="Ergon",
        careers_url="https://www.ergon.ch/de/karriere/jobs?showAllJobs=true",
        parser_path="app.services.parsers.companies.ergon:ErgonJobsParser",
        settings_map=(
            ("base_url", "ergon_jobs_base_url"),
            ("api_url", "ergon_jobs_api_url"),
            ("timeout_seconds", "ergon_jobs_timeout_seconds"),
            ("max_jobs", "ergon_jobs_max_jobs"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="logobject",
        name="LogObject",
        careers_url="https://logobject.com/karriere",
        parser_path="app.services.parsers.companies.logobject:LogObjectJobsParser",
        settings_map=(
            ("base_url", "logobject_jobs_base_url"),
            ("timeout_seconds", "logobject_jobs_timeout_seconds"),
            ("max_jobs", "logobject_jobs_max_jobs"),
            ("detail_workers", "logobject_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ti8m_switzerland",
        name="ti&m Switzerland",
        careers_url="https://www.ti8m.com/en/career#job",
        parser_path=(
            "app.services.parsers.companies.ti8m_switzerland:"
            "Ti8mSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "ti8m_switzerland_jobs_base_url"),
            ("catalog_url", "ti8m_switzerland_jobs_catalog_url"),
            ("timeout_seconds", "ti8m_switzerland_jobs_timeout_seconds"),
            ("max_jobs", "ti8m_switzerland_jobs_max_jobs"),
            ("detail_workers", "ti8m_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="novartis_switzerland",
        name="Novartis Switzerland",
        careers_url=(
            "https://www.novartis.com/careers/career-search?search_api_fulltext="
            "&country%5B%5D=LOC_CH&field_job_posted_date=All&op=Submit"
        ),
        parser_path=(
            "app.services.parsers.companies.novartis_switzerland:"
            "NovartisSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "novartis_switzerland_jobs_base_url"),
            ("timeout_seconds", "novartis_switzerland_jobs_timeout_seconds"),
            ("max_pages", "novartis_switzerland_jobs_max_pages"),
            ("max_catalog_passes", "novartis_switzerland_jobs_max_catalog_passes"),
            ("detail_workers", "novartis_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="pictet_switzerland",
        name="Pictet Switzerland",
        careers_url=(
            "https://career012.successfactors.eu/career?company=banquepict"
            "&career_ns=job_listing_summary&navBarLevel=JOB_SEARCH"
        ),
        parser_path=(
            "app.services.parsers.companies.pictet_switzerland:"
            "PictetSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "pictet_switzerland_jobs_base_url"),
            ("timeout_seconds", "pictet_switzerland_jobs_timeout_seconds"),
            ("max_jobs", "pictet_switzerland_jobs_max_jobs"),
            ("max_catalog_passes", "pictet_switzerland_jobs_max_catalog_passes"),
            ("detail_workers", "pictet_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="swiss_re",
        name="Swiss Re",
        careers_url=(
            "https://www.swissre.com/careers/switzerland-careers.html"
        ),
        parser_path="app.services.parsers.companies.swiss_re:SwissReJobsParser",
        settings_map=(
            ("base_url", "swiss_re_jobs_base_url"),
            ("search_url", "swiss_re_jobs_search_url"),
            ("timeout_seconds", "swiss_re_jobs_timeout_seconds"),
            ("max_pages", "swiss_re_jobs_max_pages"),
            ("max_catalog_passes", "swiss_re_jobs_max_catalog_passes"),
            ("detail_workers", "swiss_re_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="baloise",
        name="Baloise",
        careers_url="https://www.baloise.com/de/CH/jobs.html",
        parser_path="app.services.parsers.companies.baloise:BaloiseJobsParser",
        settings_map=(
            ("base_url", "baloise_jobs_base_url"),
            ("catalog_url", "baloise_jobs_catalog_url"),
            ("timeout_seconds", "baloise_jobs_timeout_seconds"),
            ("max_jobs", "baloise_jobs_max_jobs"),
            ("detail_workers", "baloise_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="elca",
        name="ELCA",
        careers_url=(
            "https://iaaras.fa.ocs.oraclecloud.com/"
            "hcmUI/CandidateExperience/en/sites/CX_1/jobs"
        ),
        parser_path="app.services.parsers.companies.elca:ElcaJobsParser",
        settings_map=(
            ("base_url", "elca_jobs_base_url"),
            ("api_url", "elca_jobs_api_url"),
            ("timeout_seconds", "elca_jobs_timeout_seconds"),
            ("max_pages", "elca_jobs_max_pages"),
            ("max_catalog_passes", "elca_jobs_max_catalog_passes"),
            ("detail_workers", "elca_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="aveniq",
        name="Aveniq",
        careers_url="https://aveniq.recruitee.com/",
        parser_path="app.services.parsers.companies.aveniq:AveniqJobsParser",
        settings_map=(
            ("base_url", "aveniq_jobs_base_url"),
            ("api_url", "aveniq_jobs_api_url"),
            ("timeout_seconds", "aveniq_jobs_timeout_seconds"),
            ("max_jobs", "aveniq_jobs_max_jobs"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="mimacom",
        name="Mimacom",
        careers_url="https://www.mimacom.com/jobs",
        parser_path="app.services.parsers.companies.mimacom:MimacomJobsParser",
        settings_map=(
            ("base_url", "mimacom_jobs_base_url"),
            ("timeout_seconds", "mimacom_jobs_timeout_seconds"),
            ("max_jobs", "mimacom_jobs_max_jobs"),
            ("detail_workers", "mimacom_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="unit8_switzerland",
        name="Unit8 Switzerland",
        careers_url="https://unit8.com/career/",
        parser_path=(
            "app.services.parsers.companies.unit8_switzerland:"
            "Unit8SwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "unit8_switzerland_jobs_base_url"),
            ("api_url", "unit8_switzerland_jobs_api_url"),
            ("timeout_seconds", "unit8_switzerland_jobs_timeout_seconds"),
            ("max_jobs", "unit8_switzerland_jobs_max_jobs"),
            ("detail_workers", "unit8_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="axpo_switzerland",
        name="Axpo Switzerland",
        careers_url=(
            "https://careers.axpo.com/jobs?"
            "split_view=true&query=&country=Switzerland"
        ),
        parser_path=(
            "app.services.parsers.companies.axpo_switzerland:"
            "AxpoSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "axpo_switzerland_jobs_base_url"),
            ("feed_url", "axpo_switzerland_jobs_feed_url"),
            ("timeout_seconds", "axpo_switzerland_jobs_timeout_seconds"),
            ("max_pages", "axpo_switzerland_jobs_max_pages"),
            ("max_jobs", "axpo_switzerland_jobs_max_jobs"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ringier",
        name="Ringier",
        careers_url="https://career.ringier.ch/en/career",
        parser_path="app.services.parsers.companies.ringier:RingierJobsParser",
        settings_map=(
            ("base_url", "ringier_jobs_base_url"),
            ("api_url", "ringier_jobs_api_url"),
            ("timeout_seconds", "ringier_jobs_timeout_seconds"),
            ("max_jobs", "ringier_jobs_max_jobs"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="msd",
        name="MSD",
        careers_url=(
            "https://jobs.msd.com/gb/en/search-results?"
            "rk=page-targeted-jobs-page172-prod-DZJ1ve"
        ),
        parser_path="app.services.parsers.companies.msd:MsdJobsParser",
        settings_map=(
            ("base_url", "msd_jobs_base_url"),
            ("timeout_seconds", "msd_jobs_timeout_seconds"),
            ("max_pages", "msd_jobs_max_pages"),
            ("max_catalog_passes", "msd_jobs_max_catalog_passes"),
            ("page_workers", "msd_jobs_page_workers"),
            ("detail_workers", "msd_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="srg_ssr",
        name="SRG SSR",
        careers_url="https://www.srgssr.ch/en/jobs-career/jobs",
        parser_path="app.services.parsers.companies.srg_ssr:SrgSsrJobsParser",
        settings_map=(
            ("base_url", "srg_ssr_jobs_base_url"),
            ("catalog_url", "srg_ssr_jobs_catalog_url"),
            ("timeout_seconds", "srg_ssr_jobs_timeout_seconds"),
            ("detail_workers", "srg_ssr_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ibm",
        name="IBM",
        careers_url=(
            "https://www.ibm.com/de-de/careers/search?"
            "field_keyword_05[0]=Switzerland"
        ),
        parser_path="app.services.parsers.companies.ibm:IbmJobsParser",
        settings_map=(
            ("base_url", "ibm_jobs_base_url"),
            ("api_url", "ibm_jobs_api_url"),
            ("timeout_seconds", "ibm_jobs_timeout_seconds"),
            ("max_pages", "ibm_jobs_max_pages"),
            ("max_catalog_passes", "ibm_jobs_max_catalog_passes"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="google",
        name="Google",
        careers_url=(
            "https://www.google.com/about/careers/applications/jobs/results/"
            "?location=Zurich%2C%20Switzerland"
        ),
        parser_path="app.services.parsers.companies.google:GoogleJobsParser",
        settings_map=(
            ("base_url", "google_jobs_base_url"),
            ("timeout_seconds", "google_jobs_timeout_seconds"),
            ("max_pages", "google_jobs_max_pages"),
            ("max_catalog_passes", "google_jobs_max_catalog_passes"),
            ("detail_workers", "google_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="buhler_switzerland",
        name="Bühler Schweiz",
        careers_url="https://jobs.buhlergroup.com/?lang=de",
        parser_path=(
            "app.services.parsers.companies.buhler_switzerland:"
            "BuhlerSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "buhler_switzerland_jobs_base_url"),
            ("api_url", "buhler_switzerland_jobs_api_url"),
            ("timeout_seconds", "buhler_switzerland_jobs_timeout_seconds"),
            ("max_pages", "buhler_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "buhler_switzerland_jobs_max_catalog_passes",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="oracle_switzerland",
        name="Oracle Switzerland",
        careers_url=(
            "https://careers.oracle.com/en/sites/jobsearch/jobs?"
            "lastSelectedFacet=locations&location=Switzerland&"
            "locationId=300000000106764&locationLevel=country&mode=location&"
            "selectedLocationsFacet=300000000106764"
        ),
        parser_path=(
            "app.services.parsers.companies.oracle_switzerland:"
            "OracleSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "oracle_switzerland_jobs_base_url"),
            ("api_url", "oracle_switzerland_jobs_api_url"),
            ("timeout_seconds", "oracle_switzerland_jobs_timeout_seconds"),
            ("max_pages", "oracle_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "oracle_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "oracle_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="adnovum",
        name="Adnovum",
        careers_url="https://careers.adnovum.com/search/",
        parser_path="app.services.parsers.companies.adnovum:AdnovumJobsParser",
        settings_map=(
            ("base_url", "adnovum_jobs_base_url"),
            ("timeout_seconds", "adnovum_jobs_timeout_seconds"),
            ("max_pages", "adnovum_jobs_max_pages"),
            ("max_catalog_passes", "adnovum_jobs_max_catalog_passes"),
            ("detail_workers", "adnovum_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ey_switzerland",
        name="EY Switzerland",
        careers_url=(
            "https://careers.ey.com/ey/search/?createNewAlert=false&q="
            "&locationsearch=&optionsFacetsDD_country=CH"
            "&optionsFacetsDD_customfield1="
        ),
        parser_path=(
            "app.services.parsers.companies.ey_switzerland:"
            "EySwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "ey_switzerland_jobs_base_url"),
            ("timeout_seconds", "ey_switzerland_jobs_timeout_seconds"),
            ("max_pages", "ey_switzerland_jobs_max_pages"),
            ("max_catalog_passes", "ey_switzerland_jobs_max_catalog_passes"),
            ("detail_workers", "ey_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="eth_zurich",
        name="ETH Zürich",
        careers_url="https://jobs.ethz.ch/",
        parser_path=(
            "app.services.parsers.companies.eth_zurich:EthZurichJobsParser"
        ),
        settings_map=(
            ("base_url", "eth_zurich_jobs_base_url"),
            ("timeout_seconds", "eth_zurich_jobs_timeout_seconds"),
            ("detail_workers", "eth_zurich_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="siemens_switzerland",
        name="Siemens Schweiz",
        careers_url=(
            "https://jobs.siemens.com/de_DE/externaljobs/SearchJobs/"
            "?42386=%5B812129%5D&42386_format=17546&listFilterMode=1"
            "&folderRecordsPerPage=6"
        ),
        parser_path=(
            "app.services.parsers.companies.siemens_switzerland:"
            "SiemensSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "siemens_switzerland_jobs_base_url"),
            ("timeout_seconds", "siemens_switzerland_jobs_timeout_seconds"),
            ("max_pages", "siemens_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "siemens_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "siemens_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="kpmg_switzerland",
        name="KPMG Switzerland",
        careers_url="https://kpmg.com/ch/de/karriere/offene-stellen.html",
        parser_path=(
            "app.services.parsers.companies.kpmg_switzerland:"
            "KpmgSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "kpmg_switzerland_jobs_base_url"),
            ("api_url", "kpmg_switzerland_jobs_api_url"),
            ("timeout_seconds", "kpmg_switzerland_jobs_timeout_seconds"),
            ("max_pages", "kpmg_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "kpmg_switzerland_jobs_max_catalog_passes",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="swissgrid",
        name="Swissgrid",
        careers_url="https://www.swissgrid.ch/en/home/career/jobs.html",
        parser_path="app.services.parsers.companies.swissgrid:SwissgridJobsParser",
        settings_map=(
            ("base_url", "swissgrid_jobs_base_url"),
            ("api_url", "swissgrid_jobs_api_url"),
            ("timeout_seconds", "swissgrid_jobs_timeout_seconds"),
            ("detail_workers", "swissgrid_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="suva",
        name="Suva",
        careers_url=(
            "https://jobs.suva.ch/search/?q=&searchResultView=LIST&pageNumber=0"
            "&facetFilters=%7B%7D&sortBy=&markerViewed=&carouselIndex="
        ),
        parser_path="app.services.parsers.companies.suva:SuvaJobsParser",
        settings_map=(
            ("base_url", "suva_jobs_base_url"),
            ("api_url", "suva_jobs_api_url"),
            ("timeout_seconds", "suva_jobs_timeout_seconds"),
            ("max_pages", "suva_jobs_max_pages"),
            ("max_catalog_passes", "suva_jobs_max_catalog_passes"),
            ("detail_workers", "suva_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ao_foundation",
        name="AO Foundation",
        careers_url="https://careers.aofoundation.org/search/locale=en_US",
        parser_path=(
            "app.services.parsers.companies.ao_foundation:"
            "AoFoundationJobsParser"
        ),
        settings_map=(
            ("base_url", "ao_foundation_jobs_base_url"),
            ("page_url", "ao_foundation_jobs_page_url"),
            ("timeout_seconds", "ao_foundation_jobs_timeout_seconds"),
            ("max_pages", "ao_foundation_jobs_max_pages"),
            (
                "max_catalog_passes",
                "ao_foundation_jobs_max_catalog_passes",
            ),
            ("detail_workers", "ao_foundation_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="skyguide",
        name="Skyguide",
        careers_url="https://jobs.skyguide.ch/search?locale=en_US",
        parser_path="app.services.parsers.companies.skyguide:SkyguideJobsParser",
        settings_map=(
            ("base_url", "skyguide_jobs_base_url"),
            ("timeout_seconds", "skyguide_jobs_timeout_seconds"),
            ("max_pages", "skyguide_jobs_max_pages"),
            ("max_catalog_passes", "skyguide_jobs_max_catalog_passes"),
            ("detail_workers", "skyguide_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="roche_switzerland",
        name="Roche Switzerland",
        careers_url="https://careers.roche.com/global/en/search-results",
        parser_path=(
            "app.services.parsers.companies.roche_switzerland:"
            "RocheSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "roche_switzerland_jobs_base_url"),
            ("timeout_seconds", "roche_switzerland_jobs_timeout_seconds"),
            ("max_pages", "roche_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "roche_switzerland_jobs_max_catalog_passes",
            ),
            ("page_workers", "roche_switzerland_jobs_page_workers"),
            ("detail_workers", "roche_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="logitech_switzerland",
        name="Logitech Switzerland",
        careers_url=(
            "https://logitech.wd5.myworkdayjobs.com/Logitech?"
            "locationCountry=187134fccb084a0ea9b4b95f23890dbe"
        ),
        parser_path=(
            "app.services.parsers.companies.logitech_switzerland:"
            "LogitechSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "logitech_switzerland_jobs_base_url"),
            ("timeout_seconds", "logitech_switzerland_jobs_timeout_seconds"),
            ("max_pages", "logitech_switzerland_jobs_max_pages"),
            ("detail_workers", "logitech_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="swatch_group",
        name="Swatch Group",
        careers_url=(
            "https://www.swatchgroup.com/en/job-finder?jf_country=40&domain=59"
            "&position=All&contract=All&time=All"
        ),
        parser_path=(
            "app.services.parsers.companies.swatch_group:"
            "SwatchGroupJobsParser"
        ),
        settings_map=(
            ("base_url", "swatch_group_jobs_base_url"),
            ("timeout_seconds", "swatch_group_jobs_timeout_seconds"),
            ("max_pages", "swatch_group_jobs_max_pages"),
            ("detail_workers", "swatch_group_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="amazon_switzerland",
        name="Amazon Switzerland",
        careers_url=(
            "https://www.amazon.jobs/content/en/locations/switzerland/zurich"
        ),
        parser_path=(
            "app.services.parsers.companies.amazon_switzerland:"
            "AmazonSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "amazon_switzerland_jobs_base_url"),
            ("api_url", "amazon_switzerland_jobs_api_url"),
            ("timeout_seconds", "amazon_switzerland_jobs_timeout_seconds"),
            ("max_pages", "amazon_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "amazon_switzerland_jobs_max_catalog_passes",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="cognizant_switzerland",
        name="Cognizant Technology Solutions AG",
        careers_url=(
            "https://careers.cognizant.com/global-en/jobs/?keyword="
            "&location=Switzerland&lat=&lng=&cname=Switzerland&ccode=CH"
            "&origin=global"
        ),
        parser_path=(
            "app.services.parsers.companies.cognizant_switzerland:"
            "CognizantSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "cognizant_switzerland_jobs_base_url"),
            ("timeout_seconds", "cognizant_switzerland_jobs_timeout_seconds"),
            ("max_pages", "cognizant_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "cognizant_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "cognizant_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="fisba",
        name="FISBA",
        careers_url="https://www.fisba.com/en/current-vacancies",
        parser_path="app.services.parsers.companies.fisba:FisbaJobsParser",
        settings_map=(
            ("base_url", "fisba_jobs_base_url"),
            ("timeout_seconds", "fisba_jobs_timeout_seconds"),
            ("detail_workers", "fisba_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="gritec",
        name="GRITEC",
        careers_url="https://www.gritec.ch/en/career",
        parser_path="app.services.parsers.companies.gritec:GritecJobsParser",
        settings_map=(
            ("base_url", "gritec_jobs_base_url"),
            ("timeout_seconds", "gritec_jobs_timeout_seconds"),
            ("detail_workers", "gritec_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="helbling",
        name="Helbling",
        careers_url="https://helbling.ch/de/karriere/jobs",
        parser_path="app.services.parsers.companies.helbling:HelblingJobsParser",
        settings_map=(
            ("base_url", "helbling_jobs_base_url"),
            ("timeout_seconds", "helbling_jobs_timeout_seconds"),
            ("detail_workers", "helbling_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="maerki_baumann",
        name="Maerki Baumann",
        careers_url=(
            "https://www.maerki-baumann.ch/de/unsere-bank/stellenangebote"
        ),
        parser_path=(
            "app.services.parsers.companies.maerki_baumann:"
            "MaerkiBaumannJobsParser"
        ),
        settings_map=(
            ("base_url", "maerki_baumann_jobs_base_url"),
            ("api_url", "maerki_baumann_jobs_api_url"),
            ("timeout_seconds", "maerki_baumann_jobs_timeout_seconds"),
            ("detail_workers", "maerki_baumann_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="electrosuisse",
        name="Electrosuisse",
        careers_url=(
            "https://www.electrosuisse.ch/de/karriere/offene-stellen/"
        ),
        parser_path=(
            "app.services.parsers.companies.electrosuisse:"
            "ElectrosuisseJobsParser"
        ),
        settings_map=(
            ("base_url", "electrosuisse_jobs_base_url"),
            ("api_url", "electrosuisse_jobs_api_url"),
            ("timeout_seconds", "electrosuisse_jobs_timeout_seconds"),
            ("detail_workers", "electrosuisse_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="detecon_switzerland",
        name="Detecon Switzerland",
        careers_url="https://www.detecon.com/de/jobs",
        parser_path=(
            "app.services.parsers.companies.detecon_switzerland:"
            "DeteconSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "detecon_switzerland_jobs_base_url"),
            ("timeout_seconds", "detecon_switzerland_jobs_timeout_seconds"),
            ("detail_workers", "detecon_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="lufthansa_group_switzerland",
        name="Lufthansa Group Switzerland",
        careers_url=(
            "https://apply.lufthansagroup.careers/index.php?ac=search_result"
            "&search_criterion_division%5B%5D=5926"
            "&search_criterion_division%5B%5D=9114"
            "&search_criterion_division%5B%5D=5988"
            "&search_criterion_division%5B%5D=6006"
            "&search_criterion_channel%5B%5D=12"
        ),
        parser_path=(
            "app.services.parsers.companies.lufthansa_group_switzerland:"
            "LufthansaGroupSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "lufthansa_group_switzerland_jobs_base_url"),
            ("api_url", "lufthansa_group_switzerland_jobs_api_url"),
            ("timeout_seconds", "lufthansa_group_switzerland_jobs_timeout_seconds"),
            ("max_pages", "lufthansa_group_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "lufthansa_group_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "lufthansa_group_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="adesso_switzerland",
        name="Adesso Switzerland",
        careers_url=(
            "https://www.adesso.ch/de_ch/jobs-karriere/unsere-stellenangebote/"
        ),
        parser_path=(
            "app.services.parsers.companies.adesso_switzerland:"
            "AdessoSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "adesso_switzerland_jobs_base_url"),
            ("feed_url", "adesso_switzerland_jobs_feed_url"),
            ("timeout_seconds", "adesso_switzerland_jobs_timeout_seconds"),
            ("detail_workers", "adesso_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="cudos",
        name="Cudos",
        careers_url="https://cudos.ch/de/jobs/",
        parser_path="app.services.parsers.companies.cudos:CudosJobsParser",
        settings_map=(
            ("base_url", "cudos_jobs_base_url"),
            ("timeout_seconds", "cudos_jobs_timeout_seconds"),
            ("detail_workers", "cudos_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="eraneos_switzerland",
        name="Eraneos Switzerland",
        careers_url=(
            "https://eraneos.wd3.myworkdayjobs.com/Eraneos_External_Career_Site"
        ),
        parser_path=(
            "app.services.parsers.companies.eraneos_switzerland:"
            "EraneosSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "eraneos_switzerland_jobs_base_url"),
            ("timeout_seconds", "eraneos_switzerland_jobs_timeout_seconds"),
            ("max_pages", "eraneos_switzerland_jobs_max_pages"),
            ("detail_workers", "eraneos_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bachem",
        name="Bachem",
        careers_url=(
            "https://careers.bachem.com/search/?createNewAlert=false&q="
            "&optionsFacetsDD_department=&optionsFacetsDD_shifttype="
            "&optionsFacetsDD_location=&optionsFacetsDD_country=CH"
            "&optionsFacetsDD_customfield1="
        ),
        parser_path="app.services.parsers.companies.bachem:BachemJobsParser",
        settings_map=(
            ("base_url", "bachem_jobs_base_url"),
            ("timeout_seconds", "bachem_jobs_timeout_seconds"),
            ("max_pages", "bachem_jobs_max_pages"),
            ("max_catalog_passes", "bachem_jobs_max_catalog_passes"),
            ("detail_workers", "bachem_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="georg_fischer_switzerland",
        name="Georg Fischer Switzerland",
        careers_url=(
            "https://georgfischer.wd103.myworkdayjobs.com/GeorgFischer_Careers?"
            "locationCountry=187134fccb084a0ea9b4b95f23890dbe"
        ),
        parser_path=(
            "app.services.parsers.companies.georg_fischer_switzerland:"
            "GeorgFischerSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "georg_fischer_switzerland_jobs_base_url"),
            ("timeout_seconds", "georg_fischer_switzerland_jobs_timeout_seconds"),
            ("max_pages", "georg_fischer_switzerland_jobs_max_pages"),
            ("detail_workers", "georg_fischer_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="also",
        name="ALSO",
        careers_url=(
            "https://www.also.com/ec/cms5/en_6000/6000/company/career/"
            "open-positions/index.jsp"
        ),
        parser_path="app.services.parsers.companies.also:AlsoJobsParser",
        settings_map=(
            ("base_url", "also_jobs_base_url"),
            ("api_url", "also_jobs_api_url"),
            ("timeout_seconds", "also_jobs_timeout_seconds"),
            ("detail_workers", "also_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bedag",
        name="Bedag",
        careers_url="https://www.bedag.ch/de/jobs-und-karriere/offene-stellen/",
        parser_path="app.services.parsers.companies.bedag:BedagJobsParser",
        settings_map=(
            ("base_url", "bedag_jobs_base_url"),
            ("timeout_seconds", "bedag_jobs_timeout_seconds"),
            ("detail_workers", "bedag_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="nexplore",
        name="Nexplore",
        careers_url="https://www.nexplore.ch/jobs",
        parser_path="app.services.parsers.companies.nexplore:NexploreJobsParser",
        settings_map=(
            ("base_url", "nexplore_jobs_base_url"),
            ("api_url", "nexplore_jobs_api_url"),
            ("timeout_seconds", "nexplore_jobs_timeout_seconds"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ntt_global_data_centers_switzerland",
        name="NTT Global Data Centers",
        careers_url=(
            "https://nttglobaldatacenters.wd501.myworkdayjobs.com/en-US/"
            "External/jobs?locations=0416448655001000c28517e560890000"
        ),
        parser_path=(
            "app.services.parsers.companies.ntt_global_data_centers_switzerland:"
            "NttGlobalDataCentersSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "ntt_global_data_centers_switzerland_jobs_base_url"),
            (
                "timeout_seconds",
                "ntt_global_data_centers_switzerland_jobs_timeout_seconds",
            ),
            ("max_pages", "ntt_global_data_centers_switzerland_jobs_max_pages"),
            (
                "detail_workers",
                "ntt_global_data_centers_switzerland_jobs_detail_workers",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="teradata_switzerland",
        name="Teradata Switzerland",
        careers_url="https://careers.teradata.com/jobs",
        parser_path=(
            "app.services.parsers.companies.teradata_switzerland:"
            "TeradataSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "teradata_switzerland_jobs_base_url"),
            ("api_url", "teradata_switzerland_jobs_api_url"),
            ("timeout_seconds", "teradata_switzerland_jobs_timeout_seconds"),
            ("max_pages", "teradata_switzerland_jobs_max_pages"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="swiss_life_switzerland",
        name="Swiss Life Switzerland",
        careers_url=(
            "https://www.swisslife.ch/de/ueber-uns/karriere/jobs.html#"
        ),
        parser_path=(
            "app.services.parsers.companies.swiss_life_switzerland:"
            "SwissLifeSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "swiss_life_switzerland_jobs_base_url"),
            ("catalog_url", "swiss_life_switzerland_jobs_catalog_url"),
            ("timeout_seconds", "swiss_life_switzerland_jobs_timeout_seconds"),
            ("max_pages", "swiss_life_switzerland_jobs_max_pages"),
            ("detail_workers", "swiss_life_switzerland_jobs_detail_workers"),
        ),
    ),
)

DIRECT_COMPANY_SOURCE_IDS = tuple(item.id for item in DIRECT_COMPANY_PARSERS)
SUPPORTED_VACANCY_SOURCE_IDS = (
    *AGGREGATOR_SOURCE_IDS,
    *DIRECT_COMPANY_SOURCE_IDS,
)


def direct_company_definition(source_id: str) -> DirectCompanyParserDefinition | None:
    return next(
        (item for item in DIRECT_COMPANY_PARSERS if item.id == source_id),
        None,
    )


def is_direct_company_source(source_id: str) -> bool:
    return source_id in DIRECT_COMPANY_SOURCE_IDS
