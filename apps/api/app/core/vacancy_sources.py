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
        id="gilead_switzerland",
        name="Gilead Sciences Switzerland",
        careers_url=(
            "https://gilead.wd1.myworkdayjobs.com/gileadcareers?"
            "locations=173342972c1201e6f4862b77b074df3b"
        ),
        parser_path=(
            "app.services.parsers.companies.gilead_switzerland:"
            "GileadSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "gilead_switzerland_jobs_base_url"),
            ("timeout_seconds", "gilead_switzerland_jobs_timeout_seconds"),
            ("max_pages", "gilead_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "gilead_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "gilead_switzerland_jobs_detail_workers"),
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
        id="erni_switzerland",
        name="ERNI Switzerland",
        careers_url="https://www.betterask.erni/ch-en/job-opportunities/",
        parser_path=(
            "app.services.parsers.companies.erni_switzerland:"
            "ErniSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "erni_switzerland_jobs_base_url"),
            ("catalog_url", "erni_switzerland_jobs_catalog_url"),
            ("timeout_seconds", "erni_switzerland_jobs_timeout_seconds"),
            ("detail_workers", "erni_switzerland_jobs_detail_workers"),
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
    DirectCompanyParserDefinition(
        id="sika_switzerland",
        name="Sika Switzerland",
        careers_url="https://www.sika.com/en/career/jobs.html",
        parser_path=(
            "app.services.parsers.companies.sika_switzerland:"
            "SikaSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "sika_switzerland_jobs_base_url"),
            ("catalog_url", "sika_switzerland_jobs_catalog_url"),
            ("timeout_seconds", "sika_switzerland_jobs_timeout_seconds"),
            ("max_pages", "sika_switzerland_jobs_max_pages"),
            ("max_catalog_passes", "sika_switzerland_jobs_max_catalog_passes"),
            ("detail_workers", "sika_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="centris",
        name="Centris",
        careers_url="https://www.centrisag.ch/karriere/jobs",
        parser_path="app.services.parsers.companies.centris:CentrisJobsParser",
        settings_map=(
            ("base_url", "centris_jobs_base_url"),
            ("timeout_seconds", "centris_jobs_timeout_seconds"),
            ("detail_workers", "centris_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="edorex",
        name="Edorex",
        careers_url="https://edorex.ch/jobs",
        parser_path="app.services.parsers.companies.edorex:EdorexJobsParser",
        settings_map=(
            ("base_url", "edorex_jobs_base_url"),
            ("timeout_seconds", "edorex_jobs_timeout_seconds"),
            ("detail_workers", "edorex_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="datwyler_it_infra",
        name="Dätwyler IT Infra",
        careers_url=(
            "https://careers.datwyler-itinfra.com/search/?locale=de_DE&"
            "searchResultView=LIST&facetFilters=%7B%22jobLocationCountry%22%3A%5B%22"
            "Schweiz%22%5D%7D&pageNumber=0"
        ),
        parser_path=(
            "app.services.parsers.companies.datwyler_it_infra:"
            "DatwylerItInfraJobsParser"
        ),
        settings_map=(
            ("base_url", "datwyler_it_infra_jobs_base_url"),
            ("api_url", "datwyler_it_infra_jobs_api_url"),
            ("timeout_seconds", "datwyler_it_infra_jobs_timeout_seconds"),
            ("max_pages", "datwyler_it_infra_jobs_max_pages"),
            (
                "max_catalog_passes",
                "datwyler_it_infra_jobs_max_catalog_passes",
            ),
            ("detail_workers", "datwyler_it_infra_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="komax_group",
        name="Komax Group",
        careers_url=(
            "https://jobs.komaxgroup.com/search/?q=&locationsearch=switzerland&"
            "searchResultView=LIST&pageNumber=0&facetFilters=%7B%7D&sortBy=&"
            "markerViewed=&carouselIndex="
        ),
        parser_path=(
            "app.services.parsers.companies.komax_group:"
            "KomaxGroupJobsParser"
        ),
        settings_map=(
            ("base_url", "komax_group_jobs_base_url"),
            ("api_url", "komax_group_jobs_api_url"),
            ("timeout_seconds", "komax_group_jobs_timeout_seconds"),
            ("max_pages", "komax_group_jobs_max_pages"),
            ("max_catalog_passes", "komax_group_jobs_max_catalog_passes"),
            ("detail_workers", "komax_group_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bearingpoint_switzerland",
        name="BearingPoint Switzerland",
        careers_url=(
            "https://www.bearingpoint.com/de-ch/karriere/stellenangebote/?country=CH"
        ),
        parser_path=(
            "app.services.parsers.companies.bearingpoint_switzerland:"
            "BearingpointSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "bearingpoint_switzerland_jobs_base_url"),
            ("feed_url_de", "bearingpoint_switzerland_jobs_feed_url_de"),
            ("feed_url_en", "bearingpoint_switzerland_jobs_feed_url_en"),
            ("timeout_seconds", "bearingpoint_switzerland_jobs_timeout_seconds"),
            ("max_jobs", "bearingpoint_switzerland_jobs_max_jobs"),
            (
                "max_catalog_passes",
                "bearingpoint_switzerland_jobs_max_catalog_passes",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="julius_baer_switzerland",
        name="Julius Baer Switzerland",
        careers_url=(
            "https://juliusbaer.wd3.myworkdayjobs.com/en-US/External?"
            "Location_Country=187134fccb084a0ea9b4b95f23890dbe"
        ),
        parser_path=(
            "app.services.parsers.companies.julius_baer_switzerland:"
            "JuliusBaerSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "julius_baer_switzerland_jobs_base_url"),
            ("timeout_seconds", "julius_baer_switzerland_jobs_timeout_seconds"),
            ("max_pages", "julius_baer_switzerland_jobs_max_pages"),
            ("detail_workers", "julius_baer_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bkw_switzerland",
        name="BKW Switzerland",
        careers_url="https://jobs.bkw.com/en/vacancies",
        parser_path=(
            "app.services.parsers.companies.bkw_switzerland:"
            "BkwSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "bkw_switzerland_jobs_base_url"),
            ("api_url", "bkw_switzerland_jobs_api_url"),
            ("timeout_seconds", "bkw_switzerland_jobs_timeout_seconds"),
            ("max_jobs", "bkw_switzerland_jobs_max_jobs"),
            ("detail_workers", "bkw_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="snb",
        name="Swiss National Bank (SNB)",
        careers_url="https://careers.snb.ch/search/?locale=de_DE",
        parser_path="app.services.parsers.companies.snb:SnbJobsParser",
        settings_map=(
            ("base_url", "snb_jobs_base_url"),
            ("api_url", "snb_jobs_api_url"),
            ("timeout_seconds", "snb_jobs_timeout_seconds"),
            ("max_pages", "snb_jobs_max_pages"),
            ("max_catalog_passes", "snb_jobs_max_catalog_passes"),
            ("detail_workers", "snb_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="amag_group",
        name="AMAG Group",
        careers_url="https://jobs.amag-group.ch/",
        parser_path=(
            "app.services.parsers.companies.amag_group:AmagGroupJobsParser"
        ),
        settings_map=(
            ("base_url", "amag_group_jobs_base_url"),
            ("feed_url", "amag_group_jobs_feed_url"),
            ("timeout_seconds", "amag_group_jobs_timeout_seconds"),
            ("max_jobs", "amag_group_jobs_max_jobs"),
            ("detail_workers", "amag_group_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bayer_switzerland",
        name="Bayer Switzerland",
        careers_url=(
            "https://talent.bayer.com/careers?"
            "location=Basel%2CBasel-City%2CSwitzerland&pid=562949977567067&"
            "job%20type=professional&job%20type=job%20starter&job%20type=student&"
            "job%20type=graduate&domain=bayer.com&sort_by=relevance&triggerGoButton=false"
        ),
        parser_path=(
            "app.services.parsers.companies.bayer_switzerland:"
            "BayerSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "bayer_switzerland_jobs_base_url"),
            ("api_url", "bayer_switzerland_jobs_api_url"),
            ("timeout_seconds", "bayer_switzerland_jobs_timeout_seconds"),
            ("max_pages", "bayer_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "bayer_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "bayer_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="biogen_switzerland",
        name="Biogen Switzerland",
        careers_url=(
            "https://biibhr.wd3.myworkdayjobs.com/external?"
            "locationCountry=187134fccb084a0ea9b4b95f23890dbe"
        ),
        parser_path=(
            "app.services.parsers.companies.biogen_switzerland:"
            "BiogenSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "biogen_switzerland_jobs_base_url"),
            ("timeout_seconds", "biogen_switzerland_jobs_timeout_seconds"),
            ("max_pages", "biogen_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "biogen_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "biogen_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bms_switzerland",
        name="Bristol Myers Squibb Switzerland",
        careers_url=(
            "https://jobs.bms.com/careers?domain=bms.com&start=0&location=Switzerland&"
            "pid=137482241804&sort_by=distance&filter_include_remote=1&"
            "filter_include_relocation=0"
        ),
        parser_path=(
            "app.services.parsers.companies.bms_switzerland:"
            "BmsSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "bms_switzerland_jobs_base_url"),
            ("api_url", "bms_switzerland_jobs_api_url"),
            ("detail_api_url", "bms_switzerland_jobs_detail_api_url"),
            ("timeout_seconds", "bms_switzerland_jobs_timeout_seconds"),
            ("max_pages", "bms_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "bms_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "bms_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="infoguard",
        name="InfoGuard",
        careers_url="https://www.infoguard.ch/en/career",
        parser_path="app.services.parsers.companies.infoguard:InfoGuardJobsParser",
        settings_map=(
            ("base_url", "infoguard_jobs_base_url"),
            ("timeout_seconds", "infoguard_jobs_timeout_seconds"),
            ("detail_workers", "infoguard_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="six_group",
        name="SIX",
        careers_url=(
            "https://jobs.six-group.com/search/?createNewAlert=false&q=&"
            "optionsFacetsDD_customfield2=&optionsFacetsDD_country=CH&"
            "optionsFacetsDD_customfield1="
        ),
        parser_path=(
            "app.services.parsers.companies.six_group:SixGroupJobsParser"
        ),
        settings_map=(
            ("base_url", "six_group_jobs_base_url"),
            ("timeout_seconds", "six_group_jobs_timeout_seconds"),
            ("max_pages", "six_group_jobs_max_pages"),
            ("max_catalog_passes", "six_group_jobs_max_catalog_passes"),
            ("detail_workers", "six_group_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="comerge",
        name="Comerge",
        careers_url="https://www.comerge.net/en/career#",
        parser_path="app.services.parsers.companies.comerge:ComergeJobsParser",
        settings_map=(
            ("base_url", "comerge_jobs_base_url"),
            ("timeout_seconds", "comerge_jobs_timeout_seconds"),
            ("detail_workers", "comerge_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="abraxas",
        name="Abraxas Informatik AG",
        careers_url="https://www.abraxas.ch/de/karriere/offene-stellen",
        parser_path="app.services.parsers.companies.abraxas:AbraxasJobsParser",
        settings_map=(
            ("base_url", "abraxas_jobs_base_url"),
            ("timeout_seconds", "abraxas_jobs_timeout_seconds"),
            ("detail_workers", "abraxas_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="akros",
        name="AKROS AG",
        careers_url="https://www.akros.ch/jobs/",
        parser_path="app.services.parsers.companies.akros:AkrosJobsParser",
        settings_map=(
            ("base_url", "akros_jobs_base_url"),
            ("timeout_seconds", "akros_jobs_timeout_seconds"),
            ("detail_workers", "akros_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="ametiq",
        name="amétiq ag",
        careers_url="https://ametiq.ch/jobs/",
        parser_path="app.services.parsers.companies.ametiq:AmetiqJobsParser",
        settings_map=(
            ("base_url", "ametiq_jobs_base_url"),
            ("timeout_seconds", "ametiq_jobs_timeout_seconds"),
            ("detail_workers", "ametiq_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bsi_software",
        name="BSI Software",
        careers_url="https://www.bsi-software.com/en/career/jobs",
        parser_path=(
            "app.services.parsers.companies.bsi_software:"
            "BsiSoftwareJobsParser"
        ),
        settings_map=(
            ("base_url", "bsi_software_jobs_base_url"),
            ("jobs_url", "bsi_software_jobs_catalog_url"),
            ("api_url", "bsi_software_jobs_api_url"),
            ("timeout_seconds", "bsi_software_jobs_timeout_seconds"),
            ("max_pages", "bsi_software_jobs_max_pages"),
            ("detail_workers", "bsi_software_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="cmi",
        name="CM Informatik AG",
        careers_url="https://cmi.ch/karriere/",
        parser_path="app.services.parsers.companies.cmi:CmiJobsParser",
        settings_map=(
            ("base_url", "cmi_jobs_base_url"),
            ("timeout_seconds", "cmi_jobs_timeout_seconds"),
            ("detail_workers", "cmi_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="egeli_informatik",
        name="EGELI Informatik AG",
        careers_url="https://egeli-informatik.ch/karriere/",
        parser_path=(
            "app.services.parsers.companies.egeli_informatik:"
            "EgeliInformatikJobsParser"
        ),
        settings_map=(
            ("base_url", "egeli_informatik_jobs_base_url"),
            ("portal_url", "egeli_informatik_jobs_portal_url"),
            ("timeout_seconds", "egeli_informatik_jobs_timeout_seconds"),
            ("detail_workers", "egeli_informatik_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="emineo",
        name="emineo AG",
        careers_url="https://emineo.ch/en/career/open-positions/",
        parser_path="app.services.parsers.companies.emineo:EmineoJobsParser",
        settings_map=(
            ("base_url", "emineo_jobs_base_url"),
            ("export_url", "emineo_jobs_export_url"),
            ("timeout_seconds", "emineo_jobs_timeout_seconds"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="hostpoint",
        name="Hostpoint AG",
        careers_url="https://www.hostpoint.ch/en/jobs/",
        parser_path="app.services.parsers.companies.hostpoint:HostpointJobsParser",
        settings_map=(
            ("base_url", "hostpoint_jobs_base_url"),
            ("timeout_seconds", "hostpoint_jobs_timeout_seconds"),
            ("detail_workers", "hostpoint_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="huerlimann_informatik",
        name="Hürlimann Informatik AG",
        careers_url=(
            "https://www.hi-ag.ch/unternehmen/karriere#karriere-1266-panel-2"
        ),
        parser_path=(
            "app.services.parsers.companies.huerlimann_informatik:"
            "HuerlimannInformatikJobsParser"
        ),
        settings_map=(
            ("base_url", "huerlimann_informatik_jobs_base_url"),
            ("api_url", "huerlimann_informatik_jobs_api_url"),
            ("timeout_seconds", "huerlimann_informatik_jobs_timeout_seconds"),
            ("detail_workers", "huerlimann_informatik_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="infosoft",
        name="Infosoft Systems AG",
        careers_url="https://infosoft.swiss/karriere/",
        parser_path="app.services.parsers.companies.infosoft:InfosoftJobsParser",
        settings_map=(
            ("base_url", "infosoft_jobs_base_url"),
            ("timeout_seconds", "infosoft_jobs_timeout_seconds"),
            ("detail_workers", "infosoft_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="isolutions",
        name="isolutions AG",
        careers_url="https://www.isolutions.ch/en/career/#module-1396",
        parser_path="app.services.parsers.companies.isolutions:IsolutionsJobsParser",
        settings_map=(
            ("base_url", "isolutions_jobs_base_url"),
            ("timeout_seconds", "isolutions_jobs_timeout_seconds"),
            ("detail_workers", "isolutions_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="iwf",
        name="IWF AG",
        careers_url="https://www.iwf.ch/web-solutions/jobs",
        parser_path="app.services.parsers.companies.iwf:IwfJobsParser",
        settings_map=(
            ("base_url", "iwf_jobs_base_url"),
            ("timeout_seconds", "iwf_jobs_timeout_seconds"),
            ("detail_workers", "iwf_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="loewenfels",
        name="Löwenfels Partner AG",
        careers_url="https://www.loewenfels.ch/karriere/",
        parser_path="app.services.parsers.companies.loewenfels:LoewenfelsJobsParser",
        settings_map=(
            ("base_url", "loewenfels_jobs_base_url"),
            ("api_url", "loewenfels_jobs_api_url"),
            ("timeout_seconds", "loewenfels_jobs_timeout_seconds"),
            ("detail_workers", "loewenfels_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="m_s_software_engineering",
        name="M&S Software Engineering AG",
        careers_url="https://www.m-s.ch/karriere/offene-stellen/",
        parser_path=(
            "app.services.parsers.companies.m_s_software_engineering:"
            "MSSoftwareEngineeringJobsParser"
        ),
        settings_map=(
            ("base_url", "m_s_software_engineering_jobs_base_url"),
            ("api_url", "m_s_software_engineering_jobs_api_url"),
            ("timeout_seconds", "m_s_software_engineering_jobs_timeout_seconds"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="opacc",
        name="Opacc Software AG",
        careers_url="https://jobs.opacc.ch/",
        parser_path="app.services.parsers.companies.opacc:OpaccJobsParser",
        settings_map=(
            ("base_url", "opacc_jobs_base_url"),
            ("timeout_seconds", "opacc_jobs_timeout_seconds"),
            ("detail_workers", "opacc_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="panter",
        name="Panter AG",
        careers_url="https://www.panter.ch/en/about-us/career/",
        parser_path="app.services.parsers.companies.panter:PanterJobsParser",
        settings_map=(
            ("base_url", "panter_jobs_base_url"),
            ("timeout_seconds", "panter_jobs_timeout_seconds"),
            ("detail_workers", "panter_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="digital_architects_zurich",
        name="Digital Architects Zurich GmbH",
        careers_url="https://digital-architects-zurich.ch/career/",
        parser_path=(
            "app.services.parsers.companies.digital_architects_zurich:"
            "DigitalArchitectsZurichJobsParser"
        ),
        settings_map=(
            ("base_url", "digital_architects_zurich_jobs_base_url"),
            ("timeout_seconds", "digital_architects_zurich_jobs_timeout_seconds"),
            ("detail_workers", "digital_architects_zurich_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="umb",
        name="UMB AG",
        careers_url="https://www.umb.ch/unternehmen/it-jobs-bei-umb",
        parser_path="app.services.parsers.companies.umb:UmbJobsParser",
        settings_map=(
            ("base_url", "umb_jobs_base_url"),
            ("api_url", "umb_jobs_api_url"),
            ("timeout_seconds", "umb_jobs_timeout_seconds"),
            ("max_pages", "umb_jobs_max_pages"),
            ("max_catalog_passes", "umb_jobs_max_catalog_passes"),
            ("detail_workers", "umb_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="webtouch",
        name="Webtouch GmbH",
        careers_url="https://www.webtouch.ch/karriere",
        parser_path="app.services.parsers.companies.webtouch:WebtouchJobsParser",
        settings_map=(
            ("base_url", "webtouch_jobs_base_url"),
            ("timeout_seconds", "webtouch_jobs_timeout_seconds"),
            ("max_jobs", "webtouch_jobs_max_jobs"),
            ("detail_workers", "webtouch_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="manor",
        name="Manor AG",
        careers_url="https://careers.manor.ch/de/offene-stellen/offene-stellen",
        parser_path="app.services.parsers.companies.manor:ManorJobsParser",
        settings_map=(
            ("base_url", "manor_jobs_base_url"),
            ("feed_url", "manor_jobs_feed_url"),
            ("timeout_seconds", "manor_jobs_timeout_seconds"),
            ("max_pages", "manor_jobs_max_pages"),
            ("max_catalog_passes", "manor_jobs_max_catalog_passes"),
            ("detail_workers", "manor_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="salt_mobile",
        name="Salt Mobile SA",
        careers_url=(
            "https://company.jobcloud.ch/de/job-list/"
            "1772460841133x163767963229093900?embedded=yes"
        ),
        parser_path="app.services.parsers.companies.salt_mobile:SaltMobileJobsParser",
        settings_map=(
            ("base_url", "salt_mobile_jobs_base_url"),
            ("timeout_seconds", "salt_mobile_jobs_timeout_seconds"),
            ("max_pages", "salt_mobile_jobs_max_pages"),
            ("max_catalog_passes", "salt_mobile_jobs_max_catalog_passes"),
            ("detail_workers", "salt_mobile_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="vzug",
        name="V-ZUG AG",
        careers_url="https://www.vzug.com/ch/de/jobs",
        parser_path="app.services.parsers.companies.vzug:VzugJobsParser",
        settings_map=(
            ("base_url", "vzug_jobs_base_url"),
            ("catalog_url", "vzug_jobs_catalog_url"),
            ("timeout_seconds", "vzug_jobs_timeout_seconds"),
            ("max_jobs", "vzug_jobs_max_jobs"),
            ("detail_workers", "vzug_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="lindt_spruengli_switzerland",
        name="Lindt & Sprüngli (Schweiz) AG",
        careers_url=(
            "https://lindtspruengli.wd103.myworkdayjobs.com/"
            "LindtSpruengliGroupCareers?"
            "hiringCompany=6ef234644ca31000c2704c6d47960000"
        ),
        parser_path=(
            "app.services.parsers.companies.lindt_spruengli_switzerland:"
            "LindtSpruengliSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "lindt_spruengli_switzerland_jobs_base_url"),
            ("timeout_seconds", "lindt_spruengli_switzerland_jobs_timeout_seconds"),
            ("max_pages", "lindt_spruengli_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "lindt_spruengli_switzerland_jobs_max_catalog_passes",
            ),
            (
                "detail_workers",
                "lindt_spruengli_switzerland_jobs_detail_workers",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="pwc_switzerland",
        name="PwC Switzerland",
        careers_url="https://www.pwc.ch/en/careers-with-pwc/open-positions.html",
        parser_path=(
            "app.services.parsers.companies.pwc_switzerland:"
            "PwcSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "pwc_switzerland_jobs_base_url"),
            ("api_url", "pwc_switzerland_jobs_api_url"),
            ("timeout_seconds", "pwc_switzerland_jobs_timeout_seconds"),
            ("max_pages", "pwc_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "pwc_switzerland_jobs_max_catalog_passes",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="tx_group",
        name="TX Group AG",
        careers_url="https://jobs.tx.group/jobs",
        parser_path="app.services.parsers.companies.tx_group:TxGroupJobsParser",
        settings_map=(
            ("base_url", "tx_group_jobs_base_url"),
            ("feed_url", "tx_group_jobs_feed_url"),
            ("timeout_seconds", "tx_group_jobs_timeout_seconds"),
            ("max_jobs", "tx_group_jobs_max_jobs"),
            ("max_catalog_passes", "tx_group_jobs_max_catalog_passes"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="artificialy",
        name="Artificialy SA",
        careers_url="https://www.artificialy.com/career",
        parser_path="app.services.parsers.companies.artificialy:ArtificialyJobsParser",
        settings_map=(
            ("base_url", "artificialy_jobs_base_url"),
            ("timeout_seconds", "artificialy_jobs_timeout_seconds"),
            ("max_jobs", "artificialy_jobs_max_jobs"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="cyon",
        name="cyon AG",
        careers_url="https://www.cyon.ch/ueber-cyon/jobs",
        parser_path="app.services.parsers.companies.cyon:CyonJobsParser",
        settings_map=(
            ("base_url", "cyon_jobs_base_url"),
            ("timeout_seconds", "cyon_jobs_timeout_seconds"),
            ("max_jobs", "cyon_jobs_max_jobs"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="gsk_switzerland",
        name="GSK Switzerland",
        careers_url=(
            "https://jobs.gsk.com/gb/en/search-results?"
            "keywords=&location=Switzerland&lang=en-gb"
        ),
        parser_path=(
            "app.services.parsers.companies.gsk_switzerland:"
            "GskSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "gsk_switzerland_jobs_base_url"),
            ("timeout_seconds", "gsk_switzerland_jobs_timeout_seconds"),
            ("max_pages", "gsk_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "gsk_switzerland_jobs_max_catalog_passes",
            ),
            ("page_workers", "gsk_switzerland_jobs_page_workers"),
            ("detail_workers", "gsk_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="sanofi_switzerland",
        name="Sanofi Switzerland",
        careers_url=(
            "https://jobs.sanofi.com/en/search-jobs/Switzerland/2649/2/2658434/"
            "47x00016/8x01427/50/2"
        ),
        parser_path=(
            "app.services.parsers.companies.sanofi_switzerland:"
            "SanofiSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "sanofi_switzerland_jobs_base_url"),
            ("timeout_seconds", "sanofi_switzerland_jobs_timeout_seconds"),
            ("max_pages", "sanofi_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "sanofi_switzerland_jobs_max_catalog_passes",
            ),
            ("page_workers", "sanofi_switzerland_jobs_page_workers"),
            ("detail_workers", "sanofi_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="takeda_switzerland",
        name="Takeda Switzerland",
        careers_url="https://jobs.takeda.com/search-jobs",
        parser_path=(
            "app.services.parsers.companies.takeda_switzerland:"
            "TakedaSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "takeda_switzerland_jobs_base_url"),
            ("timeout_seconds", "takeda_switzerland_jobs_timeout_seconds"),
            ("max_pages", "takeda_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "takeda_switzerland_jobs_max_catalog_passes",
            ),
            ("page_workers", "takeda_switzerland_jobs_page_workers"),
            ("detail_workers", "takeda_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="jnj_switzerland",
        name="Johnson & Johnson Switzerland",
        careers_url=(
            "https://www.careers.jnj.com/en/jobs/?"
            "search=&country=Switzerland&origin=global"
        ),
        parser_path=(
            "app.services.parsers.companies.jnj_switzerland:"
            "JnjSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "jnj_switzerland_jobs_base_url"),
            ("timeout_seconds", "jnj_switzerland_jobs_timeout_seconds"),
            ("max_pages", "jnj_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "jnj_switzerland_jobs_max_catalog_passes",
            ),
            ("page_workers", "jnj_switzerland_jobs_page_workers"),
            ("detail_workers", "jnj_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="zurich_insurance",
        name="Zurich Insurance",
        careers_url=(
            "https://www.careers.zurich.com/search/?createNewAlert=false&q="
            "&locationsearch=zurich&optionsFacetsDD_shifttype="
            "&optionsFacetsDD_department=&optionsFacetsDD_customfield3="
        ),
        parser_path=(
            "app.services.parsers.companies.zurich_insurance:"
            "ZurichInsuranceJobsParser"
        ),
        settings_map=(
            ("base_url", "zurich_insurance_jobs_base_url"),
            ("timeout_seconds", "zurich_insurance_jobs_timeout_seconds"),
            ("max_pages", "zurich_insurance_jobs_max_pages"),
            (
                "max_catalog_passes",
                "zurich_insurance_jobs_max_catalog_passes",
            ),
            ("detail_workers", "zurich_insurance_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="schneider_electric_switzerland",
        name="Schneider Electric Switzerland",
        careers_url=(
            "https://careers.se.com/jobs?lang=de-DE&country=Switzerland&page=1"
        ),
        parser_path=(
            "app.services.parsers.companies.schneider_electric_switzerland:"
            "SchneiderElectricSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "schneider_electric_switzerland_jobs_base_url"),
            (
                "timeout_seconds",
                "schneider_electric_switzerland_jobs_timeout_seconds",
            ),
            ("max_pages", "schneider_electric_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "schneider_electric_switzerland_jobs_max_catalog_passes",
            ),
            (
                "page_workers",
                "schneider_electric_switzerland_jobs_page_workers",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bosch_switzerland",
        name="Bosch Switzerland",
        careers_url="https://jobs.bosch.com/en/?pages=1&country=ch#",
        parser_path=(
            "app.services.parsers.companies.bosch_switzerland:"
            "BoschSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "bosch_switzerland_jobs_base_url"),
            ("timeout_seconds", "bosch_switzerland_jobs_timeout_seconds"),
            ("page_size", "bosch_switzerland_jobs_page_size"),
            ("max_pages", "bosch_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "bosch_switzerland_jobs_max_catalog_passes",
            ),
            ("page_workers", "bosch_switzerland_jobs_page_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="eviden_switzerland",
        name="Eviden Switzerland",
        careers_url="https://eviden.com/careers/?country=CH",
        parser_path=(
            "app.services.parsers.companies.eviden_switzerland:"
            "EvidenSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "eviden_switzerland_jobs_base_url"),
            ("timeout_seconds", "eviden_switzerland_jobs_timeout_seconds"),
            (
                "max_catalog_records",
                "eviden_switzerland_jobs_max_catalog_records",
            ),
            ("detail_workers", "eviden_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="schindler_switzerland",
        name="Schindler Group",
        careers_url=(
            "https://job.schindler.com/search/?createNewAlert=false&q="
            "&locationsearch=&optionsFacetsDD_country=CH"
        ),
        parser_path=(
            "app.services.parsers.companies.schindler_switzerland:"
            "SchindlerSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "schindler_switzerland_jobs_base_url"),
            ("timeout_seconds", "schindler_switzerland_jobs_timeout_seconds"),
            ("max_pages", "schindler_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "schindler_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "schindler_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="sonova_switzerland",
        name="Sonova Group",
        careers_url=(
            "https://www.sonova.com/careers/?query-1-job-country=switzerland"
        ),
        parser_path=(
            "app.services.parsers.companies.sonova_switzerland:"
            "SonovaSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "sonova_switzerland_jobs_base_url"),
            ("api_url", "sonova_switzerland_jobs_api_url"),
            ("timeout_seconds", "sonova_switzerland_jobs_timeout_seconds"),
            (
                "max_catalog_records",
                "sonova_switzerland_jobs_max_catalog_records",
            ),
            ("detail_workers", "sonova_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="elektro_material",
        name="Elektro-Material AG",
        careers_url=(
            "https://elektro-material.ch/de/cms/seite/"
            "offene-stellen-t33143s226453a4614994"
        ),
        parser_path=(
            "app.services.parsers.companies.elektro_material:"
            "ElektroMaterialJobsParser"
        ),
        settings_map=(
            ("base_url", "elektro_material_jobs_base_url"),
            ("cms_api_url", "elektro_material_jobs_cms_api_url"),
            (
                "smartrecruiters_api_url",
                "elektro_material_jobs_smartrecruiters_api_url",
            ),
            ("timeout_seconds", "elektro_material_jobs_timeout_seconds"),
            (
                "max_catalog_records",
                "elektro_material_jobs_max_catalog_records",
            ),
            ("detail_workers", "elektro_material_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="csl_switzerland",
        name="CSL Switzerland",
        careers_url=(
            "https://jobs.csl.com/en/jobs?"
            "filterrific%5Bwith_location3%5D=switzerland&"
            "filterrific%5Bsorted_by%5D=newest"
        ),
        parser_path=(
            "app.services.parsers.companies.csl_switzerland:"
            "CslSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "csl_switzerland_jobs_base_url"),
            ("timeout_seconds", "csl_switzerland_jobs_timeout_seconds"),
            ("max_pages", "csl_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "csl_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "csl_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="lonza_switzerland",
        name="Lonza Switzerland",
        careers_url="https://www.lonza.com/careers/job-search",
        parser_path=(
            "app.services.parsers.companies.lonza_switzerland:"
            "LonzaSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "lonza_switzerland_jobs_base_url"),
            ("timeout_seconds", "lonza_switzerland_jobs_timeout_seconds"),
            ("max_pages", "lonza_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "lonza_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "lonza_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="nestle_switzerland",
        name="Nestlé Switzerland",
        careers_url=(
            "https://www.nestle.com/jobs/search-jobs?keyword=&country=CH&"
            "location=&career_area=All"
        ),
        parser_path=(
            "app.services.parsers.companies.nestle_switzerland:"
            "NestleSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "nestle_switzerland_jobs_base_url"),
            ("timeout_seconds", "nestle_switzerland_jobs_timeout_seconds"),
            ("max_pages", "nestle_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "nestle_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "nestle_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="afry_switzerland",
        name="AFRY Switzerland",
        careers_url="https://afry.com/de-ch/karriere/verfugbare-stellen",
        parser_path=(
            "app.services.parsers.companies.afry_switzerland:"
            "AfrySwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "afry_switzerland_jobs_base_url"),
            ("catalog_url", "afry_switzerland_jobs_catalog_url"),
            ("detail_api_url", "afry_switzerland_jobs_detail_api_url"),
            ("timeout_seconds", "afry_switzerland_jobs_timeout_seconds"),
            (
                "max_catalog_records",
                "afry_switzerland_jobs_max_catalog_records",
            ),
            ("detail_workers", "afry_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="digital_realty_switzerland",
        name="Digital Realty Switzerland",
        careers_url=(
            "https://hdep.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/"
            "sites/CX/jobs?location=Switzerland&locationId=300000000361301&"
            "locationLevel=country&mode=job-location"
        ),
        parser_path=(
            "app.services.parsers.companies.digital_realty_switzerland:"
            "DigitalRealtySwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "digital_realty_switzerland_jobs_base_url"),
            ("api_url", "digital_realty_switzerland_jobs_api_url"),
            (
                "timeout_seconds",
                "digital_realty_switzerland_jobs_timeout_seconds",
            ),
            ("max_pages", "digital_realty_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "digital_realty_switzerland_jobs_max_catalog_passes",
            ),
            (
                "detail_workers",
                "digital_realty_switzerland_jobs_detail_workers",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="equans_switzerland",
        name="Equans Switzerland",
        careers_url=(
            "https://www.equans.com/join-us?jobs_offer%5BrefinementList%5D"
            "%5Bcountry_en%5D%5B0%5D=Switzerland"
        ),
        parser_path=(
            "app.services.parsers.companies.equans_switzerland:"
            "EquansSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "equans_switzerland_jobs_base_url"),
            ("search_url", "equans_switzerland_jobs_search_url"),
            ("application_id", "equans_switzerland_jobs_application_id"),
            ("api_key", "equans_switzerland_jobs_api_key"),
            ("timeout_seconds", "equans_switzerland_jobs_timeout_seconds"),
            ("max_pages", "equans_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "equans_switzerland_jobs_max_catalog_passes",
            ),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bison_group",
        name="Bison Group",
        careers_url=(
            "https://www.bison-group.com/karriere/offene-stellen/"
        ),
        parser_path=(
            "app.services.parsers.companies.bison_group:BisonGroupJobsParser"
        ),
        settings_map=(
            ("base_url", "bison_group_jobs_base_url"),
            ("api_url", "bison_group_jobs_api_url"),
            ("timeout_seconds", "bison_group_jobs_timeout_seconds"),
            ("max_pages", "bison_group_jobs_max_pages"),
            (
                "max_catalog_passes",
                "bison_group_jobs_max_catalog_passes",
            ),
            ("detail_workers", "bison_group_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="prodyna_switzerland",
        name="PRODYNA Switzerland",
        careers_url="https://www.prodyna.com/jobs?location=Zurich",
        parser_path=(
            "app.services.parsers.companies.prodyna_switzerland:"
            "ProdynaSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "prodyna_switzerland_jobs_base_url"),
            ("rss_url", "prodyna_switzerland_jobs_rss_url"),
            ("timeout_seconds", "prodyna_switzerland_jobs_timeout_seconds"),
            (
                "max_catalog_records",
                "prodyna_switzerland_jobs_max_catalog_records",
            ),
            ("detail_workers", "prodyna_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="crossing_switzerland",
        name="cross-ING Switzerland",
        careers_url=(
            "https://crossing.recruitee.com/?jobs-c88dea0d%5Bcountry%5D"
            "%5B%5D=CH"
        ),
        parser_path=(
            "app.services.parsers.companies.crossing_switzerland:"
            "CrossingSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "crossing_switzerland_jobs_base_url"),
            ("api_url", "crossing_switzerland_jobs_api_url"),
            ("timeout_seconds", "crossing_switzerland_jobs_timeout_seconds"),
            ("max_jobs", "crossing_switzerland_jobs_max_jobs"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="netapp_switzerland",
        name="NetApp Switzerland",
        careers_url=(
            "https://careers.netapp.com/location/switzerland-jobs/"
            "27600/2658434/2"
        ),
        parser_path=(
            "app.services.parsers.companies.netapp_switzerland:"
            "NetAppSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "netapp_switzerland_jobs_base_url"),
            ("timeout_seconds", "netapp_switzerland_jobs_timeout_seconds"),
            ("max_pages", "netapp_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "netapp_switzerland_jobs_max_catalog_passes",
            ),
            ("page_workers", "netapp_switzerland_jobs_page_workers"),
            ("detail_workers", "netapp_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="sharp_switzerland",
        name="Sharp Switzerland",
        careers_url="https://www.sharp.ch/de/jobs-bei-sharp",
        parser_path=(
            "app.services.parsers.companies.sharp_switzerland:"
            "SharpSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "sharp_switzerland_jobs_base_url"),
            ("timeout_seconds", "sharp_switzerland_jobs_timeout_seconds"),
            ("max_jobs", "sharp_switzerland_jobs_max_jobs"),
            ("detail_workers", "sharp_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="unisys_switzerland",
        name="Unisys Switzerland",
        careers_url=(
            "https://unisys.wd5.myworkdayjobs.com/External?"
            "locationCountry=187134fccb084a0ea9b4b95f23890dbe"
        ),
        parser_path=(
            "app.services.parsers.companies.unisys_switzerland:"
            "UnisysSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "unisys_switzerland_jobs_base_url"),
            ("timeout_seconds", "unisys_switzerland_jobs_timeout_seconds"),
            ("max_pages", "unisys_switzerland_jobs_max_pages"),
            (
                "max_catalog_passes",
                "unisys_switzerland_jobs_max_catalog_passes",
            ),
            ("detail_workers", "unisys_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="rdm_switzerland",
        name="R&M Switzerland",
        careers_url=(
            "https://www.rdm.com/career/jobs/?mf-job_country%5B0%5D=ch"
        ),
        parser_path=(
            "app.services.parsers.companies.rdm_switzerland:"
            "RdmSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "rdm_switzerland_jobs_base_url"),
            ("timeout_seconds", "rdm_switzerland_jobs_timeout_seconds"),
            ("max_jobs", "rdm_switzerland_jobs_max_jobs"),
            ("detail_workers", "rdm_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="abbvie_switzerland",
        name="AbbVie Switzerland",
        careers_url=(
            "https://careers.abbvie.com/en/jobs?q=&options=&page=1&"
            "la=47.3768866&lo=8.541694&ln=Z%C3%BCrich%2C+Switzerland&lr=100"
        ),
        parser_path=(
            "app.services.parsers.companies.abbvie_switzerland:"
            "AbbVieSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "abbvie_switzerland_jobs_base_url"),
            ("timeout_seconds", "abbvie_switzerland_jobs_timeout_seconds"),
            ("max_pages", "abbvie_switzerland_jobs_max_pages"),
            ("max_jobs", "abbvie_switzerland_jobs_max_jobs"),
            ("detail_workers", "abbvie_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="lyreco_switzerland",
        name="Lyreco Switzerland",
        careers_url=(
            "https://www.lyreco.com/group/switzerland/de/jobs?"
            "f%5B0%5D=job_location%3Adietikon%20zh"
        ),
        parser_path=(
            "app.services.parsers.companies.lyreco_switzerland:"
            "LyrecoSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "lyreco_switzerland_jobs_base_url"),
            ("timeout_seconds", "lyreco_switzerland_jobs_timeout_seconds"),
            ("max_pages", "lyreco_switzerland_jobs_max_pages"),
            ("max_jobs", "lyreco_switzerland_jobs_max_jobs"),
            ("detail_workers", "lyreco_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="adcubum_switzerland",
        name="Adcubum Switzerland",
        careers_url="https://www.adcubum.com/en/job/list",
        parser_path=(
            "app.services.parsers.companies.adcubum_switzerland:"
            "AdcubumSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "adcubum_switzerland_jobs_base_url"),
            ("timeout_seconds", "adcubum_switzerland_jobs_timeout_seconds"),
            ("max_jobs", "adcubum_switzerland_jobs_max_jobs"),
            ("detail_workers", "adcubum_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="aity",
        name="aity AG",
        careers_url="https://aity.ch/jobs",
        parser_path="app.services.parsers.companies.aity:AityJobsParser",
        settings_map=(
            ("base_url", "aity_jobs_base_url"),
            ("career_center_url", "aity_jobs_career_center_url"),
            ("timeout_seconds", "aity_jobs_timeout_seconds"),
            ("max_jobs", "aity_jobs_max_jobs"),
            ("detail_workers", "aity_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="arcon",
        name="Arcon Informatik AG",
        careers_url="https://www.arcon.ch/ict-und-abacus-jobs/#OffeneStellen",
        parser_path="app.services.parsers.companies.arcon:ArconJobsParser",
        settings_map=(
            ("base_url", "arcon_jobs_base_url"),
            ("timeout_seconds", "arcon_jobs_timeout_seconds"),
            ("max_jobs", "arcon_jobs_max_jobs"),
            ("detail_workers", "arcon_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="blueworks",
        name="blueworks AG",
        careers_url="https://join.com/companies/blue",
        parser_path=(
            "app.services.parsers.companies.blueworks:BlueworksJobsParser"
        ),
        settings_map=(
            ("base_url", "blueworks_jobs_base_url"),
            ("api_url", "blueworks_jobs_api_url"),
            ("timeout_seconds", "blueworks_jobs_timeout_seconds"),
            ("max_pages", "blueworks_jobs_max_pages"),
            ("detail_workers", "blueworks_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bossard_switzerland",
        name="Bossard Switzerland",
        careers_url=(
            "https://bossard.wd103.myworkdayjobs.com/BossardJobs?"
            "locations=d01e352fee0010065272fe1496210000"
        ),
        parser_path=(
            "app.services.parsers.companies.bossard_switzerland:"
            "BossardSwitzerlandJobsParser"
        ),
        settings_map=(
            ("base_url", "bossard_switzerland_jobs_base_url"),
            ("timeout_seconds", "bossard_switzerland_jobs_timeout_seconds"),
            ("max_pages", "bossard_switzerland_jobs_max_pages"),
            ("detail_workers", "bossard_switzerland_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="boss_info",
        name="Boss Info",
        careers_url="https://www.bossinfo.com/karriere/jobs/",
        parser_path="app.services.parsers.companies.boss_info:BossInfoJobsParser",
        settings_map=(
            ("base_url", "boss_info_jobs_base_url"),
            ("timeout_seconds", "boss_info_jobs_timeout_seconds"),
            ("max_jobs", "boss_info_jobs_max_jobs"),
            ("detail_workers", "boss_info_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="clavis_it",
        name="clavis IT ag",
        careers_url="https://www.clavisit.com/karriere/jobs",
        parser_path="app.services.parsers.companies.clavis_it:ClavisItJobsParser",
        settings_map=(
            ("base_url", "clavis_it_jobs_base_url"),
            ("timeout_seconds", "clavis_it_jobs_timeout_seconds"),
            ("max_jobs", "clavis_it_jobs_max_jobs"),
            ("detail_workers", "clavis_it_jobs_detail_workers"),
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
