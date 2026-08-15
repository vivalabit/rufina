import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { expect, it, vi } from "vitest";

import HomePage from "@/app/page";
import { formatParserFailure } from "@/lib/parser-errors";
import { installApplicationWorkspaceApiMock } from "@/test/application-workspace-harness";

const configuredAppSettings = {
  has_brightdata_api_key: true,
  brightdata_api_key_preview: "brig****-key",
  ai_backend: "openclaw_codex",
  openai_api_key_configured: true,
  openai_api_key_preview: "sk-e****-key",
  openai_api_model: "gpt-5.6-terra",
  openai_api_reasoning_effort: "medium",
  openai_api_timeout_seconds: 120,
  openai_api_max_attempts: 2,
  openai_api_retry_backoff_seconds: 0.8,
  ai_match_model: "openai/gpt-5.6-terra",
  ai_match_reasoning: "low",
  ai_match_batch_size: 1,
  ai_match_timeout_seconds: 120,
  ai_match_max_attempts: 2,
  auto_ai_match_enabled: false,
  job_screening_model: "openai/gpt-5-mini",
  job_screening_reasoning: "off",
  job_screening_batch_size: 10,
  job_screening_timeout_seconds: 60,
  job_screening_max_attempts: 2,
  job_screening_max_description_chars: 12_000,
};

it("includes the actionable provider error in parser failure summaries", () => {
  expect(
    formatParserFailure(
      "LinkedIn",
      "Bright Data API key was rejected. Replace it in Settings.",
    ),
  ).toBe(
    "LinkedIn — Bright Data API key was rejected. Replace it in Settings.",
  );
});

function importedJobData({
  id,
  title,
  source = "linkedin",
}: {
  id: string;
  title: string;
  source?:
    | "linkedin"
    | "indeed"
    | "jobs_ch"
    | "sbb"
    | "swisscom"
    | "galaxus"
    | "migros_bank"
    | "die_post"
    | "raiffeisen"
    | "bundesverwaltung"
    | "axa_schweiz"
    | "sunrise"
    | "iss"
    | "accenture"
    | "csem"
    | "deloitte"
    | "zuercher_kantonalbank"
    | "flughafen_zuerich"
    | "ubs_students_graduates"
    | "abb_switzerland"
    | "huawei_switzerland"
    | "bdo_switzerland"
    | "endress_hauser_switzerland"
    | "microsoft_switzerland"
    | "sap_switzerland"
    | "s_peers"
    | "mobiliar"
    | "emmi"
    | "sulzer_switzerland"
    | "siegfried"
    | "switch"
    | "huber_suhner_switzerland"
    | "stadler_it_switzerland"
    | "ebp_switzerland"
    | "ruag_switzerland"
    | "cyberlink"
    | "ergon"
    | "logobject"
    | "ti8m_switzerland"
    | "novartis_switzerland"
    | "pictet_switzerland"
    | "swiss_re"
    | "baloise"
    | "elca"
    | "aveniq"
    | "mimacom"
    | "unit8_switzerland"
    | "axpo_switzerland"
    | "ringier"
    | "msd"
    | "srg_ssr"
    | "ibm"
    | "google"
    | "buhler_switzerland"
    | "oracle_switzerland"
    | "adnovum"
    | "ey_switzerland"
    | "eth_zurich"
    | "siemens_switzerland"
    | "kpmg_switzerland"
    | "swissgrid"
    | "suva"
    | "ao_foundation"
    | "skyguide"
    | "roche_switzerland"
    | "logitech_switzerland"
    | "swatch_group"
    | "amazon_switzerland"
    | "cognizant_switzerland"
    | "fisba"
    | "gritec"
    | "helbling"
    | "maerki_baumann"
    | "electrosuisse"
    | "detecon_switzerland"
    | "lufthansa_group_switzerland"
    | "adesso_switzerland"
    | "cudos"
    | "eraneos_switzerland"
    | "erni_switzerland"
    | "bachem"
    | "georg_fischer_switzerland"
    | "also"
    | "bedag"
    | "nexplore"
    | "ntt_global_data_centers_switzerland"
    | "teradata_switzerland"
    | "swiss_life_switzerland"
    | "sika_switzerland"
    | "centris"
    | "edorex"
    | "datwyler_it_infra"
    | "infoguard"
    | "six_group"
    | "comerge"
    | "abraxas"
    | "akros"
    | "ametiq"
    | "bsi_software"
    | "cmi"
    | "egeli_informatik"
    | "emineo"
    | "hostpoint"
    | "huerlimann_informatik"
    | "infosoft"
    | "isolutions"
    | "iwf"
    | "loewenfels"
    | "m_s_software_engineering"
    | "opacc"
    | "panter"
    | "digital_architects_zurich"
    | "umb"
    | "webtouch"
    | "manor"
    | "salt_mobile"
    | "vzug"
    | "lindt_spruengli_switzerland";
}) {
  const sourceLabel =
    source === "indeed"
      ? "Indeed"
      : source === "jobs_ch"
        ? "jobs.ch"
        : source === "sbb"
          ? "SBB CFF FFS"
          : source === "swisscom"
            ? "Swisscom"
            : source === "galaxus"
              ? "Galaxus"
              : source === "migros_bank"
                ? "Migros Bank"
                : source === "die_post"
                  ? "Die Post"
                  : source === "raiffeisen"
                    ? "Raiffeisen"
                    : source === "bundesverwaltung"
                      ? "Bundesverwaltung"
                      : source === "axa_schweiz"
                        ? "AXA Schweiz"
                        : source === "sunrise"
                          ? "Sunrise"
                          : source === "iss"
                            ? "ISS Schweiz"
                            : source === "accenture"
                              ? "Accenture"
                              : source === "csem"
                                ? "CSEM"
                                : source === "deloitte"
                                  ? "Deloitte"
                                  : source === "zuercher_kantonalbank"
                                    ? "Zürcher Kantonalbank"
                                    : source === "flughafen_zuerich"
                                      ? "Flughafen Zürich"
                                      : source === "ubs_students_graduates"
                                        ? "UBS Students & Graduates"
                                        : source === "abb_switzerland"
                                          ? "ABB Schweiz"
                                          : source === "huawei_switzerland"
                                            ? "Huawei Switzerland"
                                            : source === "bdo_switzerland"
                                              ? "BDO Switzerland"
                                              : source ===
                                                  "endress_hauser_switzerland"
                                                ? "Endress+Hauser Switzerland"
                                                : source ===
                                                    "microsoft_switzerland"
                                                  ? "Microsoft Switzerland"
                                                  : source === "sap_switzerland"
                                                    ? "SAP Switzerland"
                                                    : source === "s_peers"
                                                      ? "s-peers"
                                                      : source === "mobiliar"
                                                        ? "Mobiliar"
                                                        : source === "emmi"
                                                          ? "Emmi"
                                                          : source ===
                                                              "sulzer_switzerland"
                                                            ? "Sulzer Switzerland"
                                                            : source ===
                                                                "siegfried"
                                                              ? "Siegfried"
                                                              : source ===
                                                                  "switch"
                                                                ? "Switch"
                                                                : source ===
                                                                    "huber_suhner_switzerland"
                                                                  ? "Huber+Suhner Switzerland"
                                                                  : source ===
                                                                      "stadler_it_switzerland"
                                                                    ? "Stadler IT Switzerland"
                                                                    : source ===
                                                                        "ebp_switzerland"
                                                                      ? "EBP Switzerland"
                                                                      : source ===
                                                                          "swiss_re"
                                                                        ? "Swiss Re"
                                                                        : source ===
                                                                            "baloise"
                                                                          ? "Baloise"
                                                                          : source ===
                                                                              "elca"
                                                                            ? "ELCA"
                                                                            : source ===
                                                                                "aveniq"
                                                                              ? "Aveniq"
                                                                              : source ===
                                                                                  "mimacom"
                                                                                ? "Mimacom"
                                                                                : source ===
                                                                                    "unit8_switzerland"
                                                                                  ? "Unit8 Switzerland"
                                                                                  : source ===
                                                                                      "msd"
                                                                                    ? "MSD"
                                                                                    : source ===
                                                                                        "srg_ssr"
                                                                                      ? "SRG SSR"
                                                                                      : source ===
                                                                                          "ibm"
                                                                                        ? "IBM"
                                                                                        : source ===
                                                                                            "google"
                                                                                          ? "Google"
                                                                                          : source ===
                                                                                              "buhler_switzerland"
                                                                                            ? "Bühler Schweiz"
                                                                                            : source ===
                                                                                                "oracle_switzerland"
                                                                                              ? "Oracle Switzerland"
                                                                                              : source ===
                                                                                                  "ey_switzerland"
                                                                                                ? "EY Switzerland"
                                                                                                : source ===
                                                                                                    "adnovum"
                                                                                                  ? "Adnovum"
                                                                                                  : source ===
                                                                                                      "eth_zurich"
                                                                                                    ? "ETH Zürich"
                                                                                                    : source ===
                                                                                                        "siemens_switzerland"
                                                                                                      ? "Siemens Schweiz"
                                                                                                      : source ===
                                                                                                          "kpmg_switzerland"
                                                                                                        ? "KPMG Switzerland"
                                                                                                        : source ===
                                                                                                            "swissgrid"
                                                                                                          ? "Swissgrid"
                                                                                                          : source ===
                                                                                                              "suva"
                                                                                                            ? "Suva"
                                                                                                            : source ===
                                                                                                                "ao_foundation"
                                                                                                              ? "AO Foundation"
                                                                                                              : source ===
                                                                                                                  "skyguide"
                                                                                                                ? "Skyguide"
                                                                                                                : source ===
                                                                                                                    "roche_switzerland"
                                                                                                                  ? "Roche Switzerland"
                                                                                                                  : source ===
                                                                                                                      "logitech_switzerland"
                                                                                                                    ? "Logitech Switzerland"
                                                                                                                    : source ===
                                                                                                                        "swatch_group"
                                                                                                                      ? "Swatch Group"
                                                                                                                      : source ===
                                                                                                                          "amazon_switzerland"
                                                                                                                        ? "Amazon Switzerland"
                                                                                                                        : source ===
                                                                                                                            "cognizant_switzerland"
                                                                                                                          ? "Cognizant Technology Solutions AG"
                                                                                                                          : source ===
                                                                                                                              "fisba"
                                                                                                                            ? "FISBA"
                                                                                                                            : source ===
                                                                                                                                "gritec"
                                                                                                                              ? "GRITEC"
                                                                                                                              : source ===
                                                                                                                                  "helbling"
                                                                                                                                ? "Helbling"
                                                                                                                                : source ===
                                                                                                                                    "maerki_baumann"
                                                                                                                                  ? "Maerki Baumann"
                                                                                                                                  : source ===
                                                                                                                                      "electrosuisse"
                                                                                                                                    ? "Electrosuisse"
                                                                                                                                    : source ===
                                                                                                                                        "detecon_switzerland"
                                                                                                                                      ? "Detecon Switzerland"
                                                                                                                                      : source ===
                                                                                                                                          "lufthansa_group_switzerland"
                                                                                                                                        ? "Lufthansa Group Switzerland"
                                                                                                                                        : source ===
                                                                                                                                            "adesso_switzerland"
                                                                                                                                          ? "Adesso Switzerland"
                                                                                                                                          : source ===
                                                                                                                                              "cudos"
                                                                                                                                            ? "Cudos"
                                                                                                                                            : source ===
                                                                                                                                                "eraneos_switzerland"
                                                                                                                                              ? "Eraneos Switzerland"
                                                                                                                                              : source ===
                                                                                                                                                  "erni_switzerland"
                                                                                                                                                ? "ERNI Switzerland"
                                                                                                                                                : source ===
                                                                                                                                                    "bachem"
                                                                                                                                                  ? "Bachem"
                                                                                                                                                  : source ===
                                                                                                                                                      "georg_fischer_switzerland"
                                                                                                                                                    ? "Georg Fischer Switzerland"
                                                                                                                                                    : source ===
                                                                                                                                                        "also"
                                                                                                                                                      ? "ALSO"
                                                                                                                                                      : source ===
                                                                                                                                                          "bedag"
                                                                                                                                                        ? "Bedag"
                                                                                                                                                        : source ===
                                                                                                                                                            "nexplore"
                                                                                                                                                          ? "Nexplore"
                                                                                                                                                          : source ===
                                                                                                                                                              "ntt_global_data_centers_switzerland"
                                                                                                                                                            ? "NTT Global Data Centers"
                                                                                                                                                            : source ===
                                                                                                                                                                "teradata_switzerland"
                                                                                                                                                              ? "Teradata Switzerland"
                                                                                                                                                              : source ===
                                                                                                                                                                  "swiss_life_switzerland"
                                                                                                                                                                ? "Swiss Life Switzerland"
                                                                                                                                                                : source ===
                                                                                                                                                                    "sika_switzerland"
                                                                                                                                                                  ? "Sika Switzerland"
                                                                                                                                                                  : source ===
                                                                                                                                                                      "centris"
                                                                                                                                                                    ? "Centris"
                                                                                                                                                                    : source ===
                                                                                                                                                                        "edorex"
                                                                                                                                                                      ? "Edorex"
                                                                                                                                                                      : source ===
                                                                                                                                                                          "datwyler_it_infra"
                                                                                                                                                                        ? "Dätwyler IT Infra"
                                                                                                                                                                        : source ===
                                                                                                                                                                            "infoguard"
                                                                                                                                                                          ? "InfoGuard"
                                                                                                                                                                          : source ===
                                                                                                                                                                              "six_group"
                                                                                                                                                                            ? "SIX"
                                                                                                                                                                            : source ===
                                                                                                                                                                                "comerge"
                                                                                                                                                                              ? "Comerge"
                                                                                                                                                                              : source ===
                                                                                                                                                                                  "abraxas"
                                                                                                                                                                                ? "Abraxas Informatik AG"
                                                                                                                                                                                : source ===
                                                                                                                                                                                    "akros"
                                                                                                                                                                                  ? "AKROS AG"
                                                                                                                                                                                  : source ===
                                                                                                                                                                                      "ametiq"
                                                                                                                                                                                    ? "amétiq ag"
                                                                                                                                                                                    : source ===
                                                                                                                                                                                        "bsi_software"
                                                                                                                                                                                      ? "BSI Software"
                                                                                                                                                                                      : source ===
                                                                                                                                                                                          "cmi"
                                                                                                                                                                                        ? "CM Informatik AG"
                                                                                                                                                                                        : source ===
                                                                                                                                                                                            "egeli_informatik"
                                                                                                                                                                                          ? "EGELI Informatik AG"
                                                                                                                                                                                          : source ===
                                                                                                                                                                                              "emineo"
                                                                                                                                                                                            ? "emineo AG"
                                                                                                                                                                                            : source ===
                                                                                                                                                                                                "hostpoint"
                                                                                                                                                                                              ? "Hostpoint AG"
                                                                                                                                                                                              : source ===
                                                                                                                                                                                                  "huerlimann_informatik"
                                                                                                                                                                                                ? "Hürlimann Informatik AG"
                                                                                                                                                                                                : source ===
                                                                                                                                                                                                    "infosoft"
                                                                                                                                                                                                  ? "Infosoft Systems AG"
                                                                                                                                                                                                  : source ===
                                                                                                                                                                                                      "isolutions"
                                                                                                                                                                                                    ? "isolutions AG"
                                                                                                                                                                                                    : source ===
                                                                                                                                                                                                        "iwf"
                                                                                                                                                                                                      ? "IWF AG"
                                                                                                                                                                                                      : source ===
                                                                                                                                                                                                          "loewenfels"
                                                                                                                                                                                                        ? "Löwenfels Partner AG"
                                                                                                                                                                                                        : source ===
                                                                                                                                                                                                            "m_s_software_engineering"
                                                                                                                                                                                                          ? "M&S Software Engineering AG"
                                                                                                                                                                                                          : source ===
                                                                                                                                                                                                              "opacc"
                                                                                                                                                                                                            ? "Opacc Software AG"
                                                                                                                                                                                                            : source ===
                                                                                                                                                                                                                "axpo_switzerland"
                                                                                                                                                                                                              ? "Axpo Switzerland"
                                                                                                                                                                                                              : source ===
                                                                                                                                                                                                                  "ringier"
                                                                                                                                                                                                                ? "Ringier"
                                                                                                                                                                                                                : source ===
                                                                                                                                                                                                                    "ruag_switzerland"
                                                                                                                                                                                                                  ? "RUAG Switzerland"
                                                                                                                                                                                                                  : source ===
                                                                                                                                                                                                                      "cyberlink"
                                                                                                                                                                                                                    ? "Cyberlink"
                                                                                                                                                                                                                    : source ===
                                                                                                                                                                                                                        "ergon"
                                                                                                                                                                                                                      ? "Ergon"
                                                                                                                                                                                                                      : source ===
                                                                                                                                                                                                                          "logobject"
                                                                                                                                                                                                                        ? "LogObject"
                                                                                                                                                                                                                        : source ===
                                                                                                                                                                                                                            "ti8m_switzerland"
                                                                                                                                                                                                                          ? "ti&m Switzerland"
                                                                                                                                                                                                                          : source ===
                                                                                                                                                                                                                              "novartis_switzerland"
                                                                                                                                                                                                                            ? "Novartis Switzerland"
                                                                                                                                                                                                                            : source ===
                                                                                                                                                                                                                                "pictet_switzerland"
                                                                                                                                                                                                                              ? "Pictet Switzerland"
                                                                                                                                                                                                                              : source ===
                                                                                                                                                                                                                                  "panter"
                                                                                                                                                                                                                                ? "Panter AG"
                                                                                                                                                                                                                                : source ===
                                                                                                                                                                                                                                    "digital_architects_zurich"
                                                                                                                                                                                                                                  ? "Digital Architects Zurich GmbH"
                                                                                                                                                                                                                                  : source ===
                                                                                                                                                                                                                                      "umb"
                                                                                                                                                                                                                                    ? "UMB AG"
                                                                                                                                                                                                                                    : source ===
                                                                                                                                                                                                                                        "webtouch"
                                                                                                                                                                                                                                      ? "Webtouch GmbH"
                                                                                                                                                                                                                                      : source ===
                                                                                                                                                                                                                                          "manor"
                                                                                                                                                                                                                                        ? "Manor AG"
                                                                                                                                                                                                                                        : source ===
                                                                                                                                                                                                                                            "salt_mobile"
                                                                                                                                                                                                                                          ? "Salt Mobile SA"
                                                                                                                                                                                                                                          : source ===
                                                                                                                                                                                                                                              "vzug"
                                                                                                                                                                                                                                            ? "V-ZUG AG"
                                                                                                                                                                                                                                            : source ===
                                                                                                                                                                                                                                                "lindt_spruengli_switzerland"
                                                                                                                                                                                                                                              ? "Lindt & Sprüngli (Schweiz) AG"
                                                                                                                                                                                                                                              : "LinkedIn";
  return {
    id,
    company:
      source === "sbb"
        ? "SBB CFF FFS"
        : source === "swisscom"
          ? "Swisscom (Schweiz) AG"
          : source === "galaxus"
            ? "Galaxus"
            : source === "migros_bank"
              ? "Migros Bank"
              : source === "die_post"
                ? "Swiss Post Ltd"
                : source === "raiffeisen"
                  ? "Raiffeisen"
                  : source === "bundesverwaltung"
                    ? "Bundesamt für Informatik BIT"
                    : source === "axa_schweiz"
                      ? "AXA Switzerland"
                      : source === "sunrise"
                        ? "Sunrise Communications AG"
                        : source === "iss"
                          ? "ISS Facility Services AG"
                          : source === "accenture"
                            ? "Accenture"
                            : source === "csem"
                              ? "CSEM"
                              : source === "deloitte"
                                ? "Deloitte"
                                : source === "zuercher_kantonalbank"
                                  ? "Zürcher Kantonalbank"
                                  : source === "flughafen_zuerich"
                                    ? "Flughafen Zürich AG"
                                    : source === "ubs_students_graduates"
                                      ? "UBS"
                                      : source === "abb_switzerland"
                                        ? "ABB"
                                        : source === "huawei_switzerland"
                                          ? "Huawei Switzerland"
                                          : source === "bdo_switzerland"
                                            ? "BDO AG"
                                            : source ===
                                                "endress_hauser_switzerland"
                                              ? "Endress+Hauser Flow Switzerland"
                                              : source ===
                                                  "microsoft_switzerland"
                                                ? "Microsoft"
                                                : source === "sap_switzerland"
                                                  ? "SAP"
                                                  : source === "s_peers"
                                                    ? "s-peers AG"
                                                    : source === "mobiliar"
                                                      ? "die Mobiliar"
                                                      : source === "emmi"
                                                        ? "Emmi"
                                                        : source ===
                                                            "sulzer_switzerland"
                                                          ? "Sulzer Management AG"
                                                          : source ===
                                                              "siegfried"
                                                            ? "Siegfried AG"
                                                            : source ===
                                                                "switch"
                                                              ? "Switch"
                                                              : source ===
                                                                  "huber_suhner_switzerland"
                                                                ? "Huber+Suhner"
                                                                : source ===
                                                                    "stadler_it_switzerland"
                                                                  ? "Stadler"
                                                                  : source ===
                                                                      "ebp_switzerland"
                                                                    ? "EBP Schweiz AG"
                                                                    : source ===
                                                                        "swiss_re"
                                                                      ? "Swiss Re"
                                                                      : source ===
                                                                          "baloise"
                                                                        ? "Baloise"
                                                                        : source ===
                                                                            "elca"
                                                                          ? "ELCA"
                                                                          : source ===
                                                                              "aveniq"
                                                                            ? "Aveniq AG"
                                                                            : source ===
                                                                                "mimacom"
                                                                              ? "Mimacom"
                                                                              : source ===
                                                                                  "unit8_switzerland"
                                                                                ? "Unit8 SA"
                                                                                : source ===
                                                                                    "msd"
                                                                                  ? "MSD"
                                                                                  : source ===
                                                                                      "srg_ssr"
                                                                                    ? "SRG SSR"
                                                                                    : source ===
                                                                                        "ibm"
                                                                                      ? "IBM"
                                                                                      : source ===
                                                                                          "google"
                                                                                        ? "Google"
                                                                                        : source ===
                                                                                            "buhler_switzerland"
                                                                                          ? "Bühler AG"
                                                                                          : source ===
                                                                                              "oracle_switzerland"
                                                                                            ? "Oracle"
                                                                                            : source ===
                                                                                                "ey_switzerland"
                                                                                              ? "EY"
                                                                                              : source ===
                                                                                                  "adnovum"
                                                                                                ? "Adnovum AG"
                                                                                                : source ===
                                                                                                    "eth_zurich"
                                                                                                  ? "ETH Zürich"
                                                                                                  : source ===
                                                                                                      "siemens_switzerland"
                                                                                                    ? "Siemens Schweiz AG"
                                                                                                    : source ===
                                                                                                        "kpmg_switzerland"
                                                                                                      ? "KPMG AG"
                                                                                                      : source ===
                                                                                                          "swissgrid"
                                                                                                        ? "Swissgrid"
                                                                                                        : source ===
                                                                                                            "suva"
                                                                                                          ? "Suva"
                                                                                                          : source ===
                                                                                                              "ao_foundation"
                                                                                                            ? "AO Foundation"
                                                                                                            : source ===
                                                                                                                "skyguide"
                                                                                                              ? "Skyguide"
                                                                                                              : source ===
                                                                                                                  "roche_switzerland"
                                                                                                                ? "Roche"
                                                                                                                : source ===
                                                                                                                    "logitech_switzerland"
                                                                                                                  ? "Logitech"
                                                                                                                  : source ===
                                                                                                                      "swatch_group"
                                                                                                                    ? "Tissot Ltd"
                                                                                                                    : source ===
                                                                                                                        "amazon_switzerland"
                                                                                                                      ? "AWS EMEA SARL (Switzerland Branch)"
                                                                                                                      : source ===
                                                                                                                          "cognizant_switzerland"
                                                                                                                        ? "Cognizant Technology Solutions AG"
                                                                                                                        : source ===
                                                                                                                            "fisba"
                                                                                                                          ? "FISBA AG"
                                                                                                                          : source ===
                                                                                                                              "gritec"
                                                                                                                            ? "GRITEC AG"
                                                                                                                            : source ===
                                                                                                                                "helbling"
                                                                                                                              ? "Helbling"
                                                                                                                              : source ===
                                                                                                                                  "maerki_baumann"
                                                                                                                                ? "Maerki Baumann & Co. AG"
                                                                                                                                : source ===
                                                                                                                                    "electrosuisse"
                                                                                                                                  ? "Electrosuisse"
                                                                                                                                  : source ===
                                                                                                                                      "detecon_switzerland"
                                                                                                                                    ? "Detecon (Schweiz) AG"
                                                                                                                                    : source ===
                                                                                                                                        "lufthansa_group_switzerland"
                                                                                                                                      ? "Swiss International Air Lines AG"
                                                                                                                                      : source ===
                                                                                                                                          "adesso_switzerland"
                                                                                                                                        ? "adesso Schweiz AG"
                                                                                                                                        : source ===
                                                                                                                                            "cudos"
                                                                                                                                          ? "Cudos AG"
                                                                                                                                          : source ===
                                                                                                                                              "eraneos_switzerland"
                                                                                                                                            ? "Eraneos Switzerland AG"
                                                                                                                                            : source ===
                                                                                                                                                "erni_switzerland"
                                                                                                                                              ? "ERNI Schweiz AG"
                                                                                                                                              : source ===
                                                                                                                                                  "bachem"
                                                                                                                                                ? "Bachem AG"
                                                                                                                                                : source ===
                                                                                                                                                    "georg_fischer_switzerland"
                                                                                                                                                  ? "Georg Fischer Rohrleitungssysteme AG"
                                                                                                                                                  : source ===
                                                                                                                                                      "also"
                                                                                                                                                    ? "ALSO Holding AG"
                                                                                                                                                    : source ===
                                                                                                                                                        "bedag"
                                                                                                                                                      ? "Bedag Informatik AG"
                                                                                                                                                      : source ===
                                                                                                                                                          "nexplore"
                                                                                                                                                        ? "Nexplore AG"
                                                                                                                                                        : source ===
                                                                                                                                                            "ntt_global_data_centers_switzerland"
                                                                                                                                                          ? "NTT Global Data Centers"
                                                                                                                                                          : source ===
                                                                                                                                                              "teradata_switzerland"
                                                                                                                                                            ? "Teradata"
                                                                                                                                                            : source ===
                                                                                                                                                                "swiss_life_switzerland"
                                                                                                                                                              ? "Swiss Life AG"
                                                                                                                                                              : source ===
                                                                                                                                                                  "sika_switzerland"
                                                                                                                                                                ? "Sika AG"
                                                                                                                                                                : source ===
                                                                                                                                                                    "centris"
                                                                                                                                                                  ? "Centris AG"
                                                                                                                                                                  : source ===
                                                                                                                                                                      "edorex"
                                                                                                                                                                    ? "Edorex AG"
                                                                                                                                                                    : source ===
                                                                                                                                                                        "datwyler_it_infra"
                                                                                                                                                                      ? "Dätwyler IT Infra"
                                                                                                                                                                      : source ===
                                                                                                                                                                          "infoguard"
                                                                                                                                                                        ? "InfoGuard AG"
                                                                                                                                                                        : source ===
                                                                                                                                                                            "six_group"
                                                                                                                                                                          ? "SIX"
                                                                                                                                                                          : source ===
                                                                                                                                                                              "comerge"
                                                                                                                                                                            ? "Comerge AG"
                                                                                                                                                                            : source ===
                                                                                                                                                                                "abraxas"
                                                                                                                                                                              ? "Abraxas Informatik AG"
                                                                                                                                                                              : source ===
                                                                                                                                                                                  "akros"
                                                                                                                                                                                ? "AKROS AG"
                                                                                                                                                                                : source ===
                                                                                                                                                                                    "ametiq"
                                                                                                                                                                                  ? "amétiq ag"
                                                                                                                                                                                  : source ===
                                                                                                                                                                                      "bsi_software"
                                                                                                                                                                                    ? "BSI Software"
                                                                                                                                                                                    : source ===
                                                                                                                                                                                        "cmi"
                                                                                                                                                                                      ? "CM Informatik AG"
                                                                                                                                                                                      : source ===
                                                                                                                                                                                          "egeli_informatik"
                                                                                                                                                                                        ? "EGELI Informatik AG"
                                                                                                                                                                                        : source ===
                                                                                                                                                                                            "emineo"
                                                                                                                                                                                          ? "emineo AG"
                                                                                                                                                                                          : source ===
                                                                                                                                                                                              "hostpoint"
                                                                                                                                                                                            ? "Hostpoint AG"
                                                                                                                                                                                            : source ===
                                                                                                                                                                                                "huerlimann_informatik"
                                                                                                                                                                                              ? "Hürlimann Informatik AG"
                                                                                                                                                                                              : source ===
                                                                                                                                                                                                  "infosoft"
                                                                                                                                                                                                ? "Infosoft Systems AG"
                                                                                                                                                                                                : source ===
                                                                                                                                                                                                    "isolutions"
                                                                                                                                                                                                  ? "isolutions AG"
                                                                                                                                                                                                  : source ===
                                                                                                                                                                                                      "iwf"
                                                                                                                                                                                                    ? "IWF AG"
                                                                                                                                                                                                    : source ===
                                                                                                                                                                                                        "loewenfels"
                                                                                                                                                                                                      ? "Löwenfels Partner AG"
                                                                                                                                                                                                      : source ===
                                                                                                                                                                                                          "m_s_software_engineering"
                                                                                                                                                                                                        ? "M&S Software Engineering AG"
                                                                                                                                                                                                        : source ===
                                                                                                                                                                                                            "opacc"
                                                                                                                                                                                                          ? "Opacc Software AG"
                                                                                                                                                                                                          : source ===
                                                                                                                                                                                                              "axpo_switzerland"
                                                                                                                                                                                                            ? "Axpo Group"
                                                                                                                                                                                                            : source ===
                                                                                                                                                                                                                "ringier"
                                                                                                                                                                                                              ? "Ringier AG"
                                                                                                                                                                                                              : source ===
                                                                                                                                                                                                                  "ruag_switzerland"
                                                                                                                                                                                                                ? "RUAG AG"
                                                                                                                                                                                                                : source ===
                                                                                                                                                                                                                    "cyberlink"
                                                                                                                                                                                                                  ? "Cyberlink AG"
                                                                                                                                                                                                                  : source ===
                                                                                                                                                                                                                      "ergon"
                                                                                                                                                                                                                    ? "Ergon Informatik AG"
                                                                                                                                                                                                                    : source ===
                                                                                                                                                                                                                        "logobject"
                                                                                                                                                                                                                      ? "LogObject AG"
                                                                                                                                                                                                                      : source ===
                                                                                                                                                                                                                          "ti8m_switzerland"
                                                                                                                                                                                                                        ? "ti&m AG"
                                                                                                                                                                                                                        : source ===
                                                                                                                                                                                                                            "novartis_switzerland"
                                                                                                                                                                                                                          ? "Novartis"
                                                                                                                                                                                                                          : source ===
                                                                                                                                                                                                                              "pictet_switzerland"
                                                                                                                                                                                                                            ? "Pictet"
                                                                                                                                                                                                                            : source ===
                                                                                                                                                                                                                                "panter"
                                                                                                                                                                                                                              ? "Panter AG"
                                                                                                                                                                                                                              : source ===
                                                                                                                                                                                                                                  "digital_architects_zurich"
                                                                                                                                                                                                                                ? "Digital Architects Zurich GmbH"
                                                                                                                                                                                                                                : source ===
                                                                                                                                                                                                                                    "umb"
                                                                                                                                                                                                                                  ? "UMB AG"
                                                                                                                                                                                                                                  : source ===
                                                                                                                                                                                                                                      "webtouch"
                                                                                                                                                                                                                                    ? "Webtouch GmbH"
                                                                                                                                                                                                                                    : source ===
                                                                                                                                                                                                                                        "manor"
                                                                                                                                                                                                                                      ? "Manor AG"
                                                                                                                                                                                                                                      : source ===
                                                                                                                                                                                                                                          "salt_mobile"
                                                                                                                                                                                                                                        ? "Salt Mobile SA"
                                                                                                                                                                                                                                        : source ===
                                                                                                                                                                                                                                            "vzug"
                                                                                                                                                                                                                                          ? "V-ZUG AG"
                                                                                                                                                                                                                                          : source ===
                                                                                                                                                                                                                                              "lindt_spruengli_switzerland"
                                                                                                                                                                                                                                            ? "Lindt & Sprüngli (Schweiz) AG"
                                                                                                                                                                                                                                            : "Example AG",
    title,
    location: "Zurich",
    type: "Full-time",
    salary: "Not specified",
    posted: sourceLabel,
    experience: "Entry level",
    department: `${sourceLabel} import`,
    match: 50,
    logo:
      source === "sbb" ||
      source === "swisscom" ||
      source === "galaxus" ||
      source === "migros_bank" ||
      source === "die_post" ||
      source === "raiffeisen" ||
      source === "bundesverwaltung" ||
      source === "axa_schweiz" ||
      source === "sunrise" ||
      source === "iss" ||
      source === "accenture" ||
      source === "csem" ||
      source === "deloitte" ||
      source === "zuercher_kantonalbank" ||
      source === "flughafen_zuerich" ||
      source === "ubs_students_graduates" ||
      source === "abb_switzerland" ||
      source === "huawei_switzerland" ||
      source === "bdo_switzerland" ||
      source === "endress_hauser_switzerland" ||
      source === "microsoft_switzerland" ||
      source === "sap_switzerland" ||
      source === "s_peers" ||
      source === "mobiliar" ||
      source === "emmi" ||
      source === "sulzer_switzerland" ||
      source === "siegfried" ||
      source === "switch" ||
      source === "huber_suhner_switzerland" ||
      source === "stadler_it_switzerland" ||
      source === "ebp_switzerland" ||
      source === "ruag_switzerland" ||
      source === "cyberlink" ||
      source === "ergon" ||
      source === "logobject" ||
      source === "ti8m_switzerland" ||
      source === "novartis_switzerland" ||
      source === "pictet_switzerland" ||
      source === "swiss_re" ||
      source === "baloise" ||
      source === "elca" ||
      source === "aveniq" ||
      source === "mimacom" ||
      source === "unit8_switzerland" ||
      source === "axpo_switzerland" ||
      source === "ringier" ||
      source === "msd" ||
      source === "srg_ssr" ||
      source === "ibm" ||
      source === "google" ||
      source === "buhler_switzerland" ||
      source === "oracle_switzerland" ||
      source === "adnovum" ||
      source === "ey_switzerland" ||
      source === "eth_zurich" ||
      source === "siemens_switzerland" ||
      source === "kpmg_switzerland" ||
      source === "swissgrid" ||
      source === "suva" ||
      source === "ao_foundation" ||
      source === "skyguide" ||
      source === "roche_switzerland" ||
      source === "logitech_switzerland" ||
      source === "swatch_group" ||
      source === "amazon_switzerland" ||
      source === "cognizant_switzerland" ||
      source === "fisba" ||
      source === "gritec" ||
      source === "helbling" ||
      source === "maerki_baumann" ||
      source === "electrosuisse" ||
      source === "detecon_switzerland" ||
      source === "lufthansa_group_switzerland" ||
      source === "adesso_switzerland" ||
      source === "cudos" ||
      source === "eraneos_switzerland" ||
      source === "erni_switzerland" ||
      source === "bachem" ||
      source === "georg_fischer_switzerland" ||
      source === "also" ||
      source === "bedag" ||
      source === "nexplore" ||
      source === "ntt_global_data_centers_switzerland" ||
      source === "teradata_switzerland" ||
      source === "swiss_life_switzerland" ||
      source === "sika_switzerland" ||
      source === "centris" ||
      source === "edorex" ||
      source === "datwyler_it_infra" ||
      source === "infoguard" ||
      source === "six_group" ||
      source === "comerge" ||
      source === "abraxas" ||
      source === "akros" ||
      source === "ametiq" ||
      source === "bsi_software" ||
      source === "cmi" ||
      source === "egeli_informatik" ||
      source === "emineo" ||
      source === "hostpoint" ||
      source === "huerlimann_informatik" ||
      source === "infosoft" ||
      source === "isolutions" ||
      source === "iwf" ||
      source === "loewenfels" ||
      source === "m_s_software_engineering" ||
      source === "opacc" ||
      source === "panter" ||
      source === "digital_architects_zurich" ||
      source === "umb" ||
      source === "webtouch" ||
      source === "manor" ||
      source === "salt_mobile" ||
      source === "vzug" ||
      source === "lindt_spruengli_switzerland"
        ? "company"
        : source,
    overview: `Imported ${title}`,
    responsibilities: ["Review vacancy"],
    requirements: ["Entry level"],
    skills: [sourceLabel],
    recommendations: [],
    companyInfo: "Example vacancy",
    reviews: [],
    similarJobs: [],
    addedAt: new Date().toISOString(),
  };
}

it("deletes a legacy supporting document and hides stored cover letters", async () => {
  window.history.replaceState(null, "", "#profile");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const profileUpdates: Array<Record<string, unknown>> = [];
  let storedProfile: Record<string, unknown> = {
    name: "Eduard Ishchenko",
    documents: JSON.stringify([
      {
        title: "Legacy CV",
        category: "CV / Resume",
        language: "English",
        file_name: "legacy-cv.docx",
        file_size: "60 KB",
        file_type:
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_at: "2026-07-20T10:00:00.000Z",
        data_url:
          "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cv",
      },
      {
        title: "Legacy Cover Letter",
        category: "Cover Letter",
        language: "German",
        file_name: "legacy-cover.docx",
        file_size: "37 KB",
        file_type:
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        uploaded_at: "2026-07-20T10:00:00.000Z",
        data_url:
          "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,cover",
      },
    ]),
  };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/profile" && method === "GET")
      return Response.json(storedProfile);
    if (url.pathname === "/profile" && method === "PUT") {
      storedProfile = JSON.parse(String(init?.body)) as Record<string, unknown>;
      profileUpdates.push(storedProfile);
      return Response.json(storedProfile);
    }
    if (url.pathname === "/settings" && method === "GET")
      return Response.json(configuredAppSettings);
    if (
      (url.pathname === "/applications" ||
        url.pathname === "/applications/events") &&
      method === "PUT"
    ) {
      return Response.json([]);
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  const legacyCv = await screen.findByText("Legacy CV");
  const legacyCvCard = legacyCv.closest("article");
  expect(legacyCvCard).not.toBeNull();
  fireEvent.click(
    within(legacyCvCard!).getByRole("button", { name: "Delete document" }),
  );

  await waitFor(() =>
    expect(screen.queryByText("Legacy CV")).not.toBeInTheDocument(),
  );
  expect(screen.queryByText("Legacy Cover Letter")).not.toBeInTheDocument();
  expect(profileUpdates).toHaveLength(1);
  const savedDocuments = JSON.parse(
    String(profileUpdates[0].documents),
  ) as Array<{ id: string; title: string }>;
  expect(savedDocuments).toEqual([
    expect.objectContaining({
      id: "legacy-document-1",
      title: "Legacy Cover Letter",
    }),
  ]);
});

it("offers CV / Resume as a supporting document type", async () => {
  window.history.replaceState(null, "", "#profile");
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/profile" && method === "GET") {
      return Response.json({ name: "Eduard Ishchenko", documents: "" });
    }
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json(configuredAppSettings);
    }
    if (
      (url.pathname === "/applications" ||
        url.pathname === "/applications/events" ||
        url.pathname === "/jobs/dismissed-ids") &&
      method === "PUT"
    ) {
      return Response.json([]);
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  fireEvent.click(await screen.findByRole("button", { name: "Add document" }));
  const typeSelect = screen.getByRole("combobox", { name: "Type" });
  expect(
    within(typeSelect).getByRole("option", { name: "CV / Resume" }),
  ).toBeInTheDocument();
  expect(
    within(typeSelect).queryByRole("option", { name: "Cover Letter" }),
  ).not.toBeInTheDocument();

  fireEvent.change(typeSelect, { target: { value: "CV / Resume" } });
  const languageLabel = screen
    .getByText("Document language", { exact: true })
    .closest("label");
  expect(languageLabel).not.toBeNull();
  expect(within(languageLabel!).getByRole("combobox")).toBeInTheDocument();
  expect(screen.getByText(/DOCX under 5MB/)).toBeInTheDocument();
});

it("saves a selectable AI backend without overwriting unrelated settings", async () => {
  window.history.replaceState(null, "", "#settings");
  const requests: Array<{
    path: string;
    method: string;
    body?: Record<string, unknown>;
  }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    const body = init?.body
      ? (JSON.parse(String(init.body)) as Record<string, unknown>)
      : undefined;
    requests.push({ path: url.pathname, method, body });

    if (url.pathname === "/job-search/configs" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET")
      return Response.json(configuredAppSettings);
    if (url.pathname === "/settings" && method === "PUT") {
      return Response.json({ ...configuredAppSettings, ...body });
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  expect(
    await screen.findByText("OpenAI API key saved but not in use"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/sk-e\*\*\*\*-key remains stored/),
  ).toBeInTheDocument();
  expect(screen.getByText("brig****-key")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Show current key" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Copy" }),
  ).not.toBeInTheDocument();
  const openAiMode = screen.getByRole("radio", { name: /OpenAI API/ });
  const openClawMode = screen.getByRole("radio", {
    name: /Codex credits via OpenClaw/,
  });
  expect(openClawMode).toBeChecked();
  fireEvent.click(openAiMode);
  expect(openAiMode).toBeChecked();
  expect(
    screen.getByText("Saved key: sk-e****-key. Leave blank to keep it."),
  ).toBeInTheDocument();
  fireEvent.click(openClawMode);
  expect(screen.queryByLabelText("OpenAI API key")).not.toBeInTheDocument();
  expect(
    screen.getByText("OpenAI API key saved but not in use"),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Vacancy pre-screening model"), {
    target: { value: "openai/gpt-5-mini-fast" },
  });
  fireEvent.change(
    screen.getByRole("combobox", { name: "Vacancy pre-screening reasoning" }),
    {
      target: { value: "low" },
    },
  );
  fireEvent.change(screen.getByLabelText("Full AI Match model"), {
    target: { value: "openai/gpt-5.6-sol" },
  });
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "Full AI Match batch size" }),
    {
      target: { value: "4" },
    },
  );
  fireEvent.click(screen.getByRole("switch", { name: "Auto AI Match" }));
  fireEvent.click(screen.getByRole("button", { name: "Save AI settings" }));
  await waitFor(() => {
    expect(
      requests.filter(
        (request) => request.path === "/settings" && request.method === "PUT",
      ),
    ).toHaveLength(1);
  });
  const openClawUpdate = requests
    .filter(
      (request) => request.path === "/settings" && request.method === "PUT",
    )
    .at(-1)?.body;
  expect(openClawUpdate).toMatchObject({
    ai_backend: "openclaw_codex",
    ai_match_model: "openai/gpt-5.6-sol",
    ai_match_batch_size: 4,
    auto_ai_match_enabled: true,
    job_screening_model: "openai/gpt-5-mini-fast",
    job_screening_reasoning: "low",
  });
  expect(openClawUpdate).not.toHaveProperty("openai_api_key");
  await screen.findByText("AI backend settings saved and activated");
  fireEvent.click(screen.getByRole("radio", { name: /OpenAI API/ }));
  fireEvent.change(
    screen.getByRole("combobox", { name: "OpenAI reasoning effort" }),
    {
      target: { value: "high" },
    },
  );
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "OpenAI timeout seconds" }),
    {
      target: { value: "90" },
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Save AI settings" }));

  await waitFor(() => {
    expect(
      requests.filter(
        (request) => request.path === "/settings" && request.method === "PUT",
      ),
    ).toHaveLength(2);
  });
  const update = requests
    .filter(
      (request) => request.path === "/settings" && request.method === "PUT",
    )
    .at(-1)?.body;
  expect(update).toMatchObject({
    ai_backend: "openai_api",
    openai_api_model: "gpt-5.6-terra",
    openai_api_reasoning_effort: "high",
    openai_api_timeout_seconds: 90,
    openai_api_max_attempts: 2,
    openai_api_retry_backoff_seconds: 0.8,
    ai_match_model: "openai/gpt-5.6-sol",
    ai_match_reasoning: "low",
    ai_match_batch_size: 4,
    ai_match_timeout_seconds: 120,
    ai_match_max_attempts: 2,
    job_screening_model: "openai/gpt-5-mini-fast",
    job_screening_reasoning: "low",
    job_screening_batch_size: 10,
    job_screening_timeout_seconds: 60,
    job_screening_max_attempts: 2,
    job_screening_max_description_chars: 12_000,
  });
  expect(update).not.toHaveProperty("openai_api_key");
  expect(update).not.toHaveProperty("brightdata_api_key");

  fireEvent.click(
    screen.getByRole("button", { name: "Delete saved OpenAI API key" }),
  );
  await waitFor(() => {
    expect(
      requests.filter(
        (request) => request.path === "/settings" && request.method === "PUT",
      ),
    ).toHaveLength(3);
  });
  const deleteUpdate = requests
    .filter(
      (request) => request.path === "/settings" && request.method === "PUT",
    )
    .at(-1)?.body;
  expect(deleteUpdate).toEqual({
    ai_backend: "openclaw_codex",
    openai_api_key: "",
  });
});

it("validates OpenAI API mode before saving", async () => {
  window.history.replaceState(null, "", "#settings");
  const requests: Array<{
    path: string;
    method: string;
    body?: Record<string, unknown>;
  }> = [];
  const unconfiguredSettings = {
    ...configuredAppSettings,
    openai_api_key_configured: false,
    openai_api_key_preview: "",
  };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    const body = init?.body
      ? (JSON.parse(String(init.body)) as Record<string, unknown>)
      : undefined;
    requests.push({ path: url.pathname, method, body });

    if (url.pathname === "/job-search/configs" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET")
      return Response.json(unconfiguredSettings);
    if (url.pathname === "/settings" && method === "PUT")
      return Response.json({
        ...unconfiguredSettings,
        ...body,
        openai_api_key_configured: true,
        openai_api_key_preview: "sk-t****-key",
      });
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  await screen.findByDisplayValue("openai/gpt-5-mini");
  const openAiMode = screen.getByRole("radio", { name: /OpenAI API/ });
  fireEvent.click(openAiMode);
  await waitFor(() => expect(openAiMode).toBeChecked());
  const saveButton = screen.getByRole("button", { name: "Save AI settings" });
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Add an OpenAI API key before enabling this mode.",
  );
  expect(saveButton).toBeDisabled();

  fireEvent.change(screen.getByLabelText("OpenAI API key"), {
    target: { value: "sk-test-key" },
  });
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "OpenAI timeout seconds" }),
    { target: { value: "5" } },
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "OpenAI timeout must be between 10 and 600 seconds.",
  );
  expect(saveButton).toBeDisabled();

  fireEvent.change(
    screen.getByRole("spinbutton", { name: "OpenAI timeout seconds" }),
    { target: { value: "90" } },
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(saveButton).toBeEnabled();
  fireEvent.click(saveButton);

  await waitFor(() =>
    expect(
      requests.some(
        (request) => request.path === "/settings" && request.method === "PUT",
      ),
    ).toBe(true),
  );
  const update = requests.find(
    (request) => request.path === "/settings" && request.method === "PUT",
  )?.body;
  expect(update).toMatchObject({
    ai_backend: "openai_api",
    openai_api_key: "sk-test-key",
    openai_api_timeout_seconds: 90,
  });
});

it("adds a manual vacancy to Jobs, persists it, and starts AI analysis", async () => {
  window.history.replaceState(null, "", "#jobs");
  const requests: Array<{ path: string; method: string; body?: unknown }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    const body = init?.body
      ? (JSON.parse(String(init.body)) as unknown)
      : undefined;
    requests.push({ path: url.pathname, method, body });

    if (url.pathname === "/job-search/configs" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs" && method === "PUT") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json({
        has_brightdata_api_key: false,
        brightdata_api_key_preview: "",
      });
    }
    if (url.pathname === "/jobs/ai-match/run" && method === "POST") {
      return Response.json(
        {
          runId: "manual-match-run",
          status: "queued",
          total: 1,
          processed: 0,
          updatedJobs: [],
        },
        { status: 202 },
      );
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  fireEvent.click(await screen.findByRole("button", { name: "Add vacancy" }));
  const dialog = screen.getByRole("dialog", { name: "Add vacancy" });
  expect(dialog).toBeInTheDocument();

  fireEvent.change(within(dialog).getByLabelText("Role title *"), {
    target: { value: "Backend Engineer" },
  });
  fireEvent.change(within(dialog).getByLabelText("Company *"), {
    target: { value: "Acme" },
  });
  fireEvent.change(within(dialog).getByLabelText("Location"), {
    target: { value: "Zurich / Remote" },
  });
  fireEvent.change(within(dialog).getByLabelText("Vacancy description *"), {
    target: {
      value:
        "Build Python services and maintain PostgreSQL systems. Five years of backend experience required.",
    },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Add and analyze" }),
  );

  expect(await screen.findAllByText("Backend Engineer")).not.toHaveLength(0);
  expect(
    screen.getByRole("button", { name: "Force AI match rerun" }),
  ).toBeDisabled();

  await waitFor(() => {
    expect(
      requests.some(
        (request) => request.path === "/jobs" && request.method === "PUT",
      ),
    ).toBe(true);
    expect(
      requests.some(
        (request) =>
          request.path === "/jobs/ai-match/run" && request.method === "POST",
      ),
    ).toBe(true);
  });
  expect(requests.some((request) => request.path === "/job-search/run")).toBe(
    false,
  );

  const persistedRequest = requests.find(
    (request) => request.path === "/jobs" && request.method === "PUT",
  );
  const persistedJob = (
    persistedRequest?.body as {
      jobs: Array<{ data: { title: string; logo: string } }>;
    }
  ).jobs[0].data;
  expect(persistedJob).toMatchObject({
    title: "Backend Engineer",
    logo: "manual",
  });

  const analysisRequest = requests.find(
    (request) =>
      request.path === "/jobs/ai-match/run" && request.method === "POST",
  );
  expect(
    (analysisRequest?.body as { jobs: Array<{ data: { overview: string } }> })
      .jobs[0].data.overview,
  ).toContain("Python services");

  const locallyStoredJobs = JSON.parse(
    window.localStorage.getItem("tasko.importedJobs.v1") ?? "[]",
  ) as Array<{ title: string }>;
  expect(
    locallyStoredJobs.some((job) => job.title === "Backend Engineer"),
  ).toBe(true);
});

it("searches LinkedIn, Indeed, and jobs.ch together when all sources are selected", async () => {
  window.history.replaceState(null, "", "#jobs");
  const requests: Array<{ path: string; method: string }> = [];
  const requestUrls: string[] = [];
  const runBodies: Array<Record<string, unknown>> = [];
  let storedJobs: Array<{ id: string; data: unknown }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    requests.push({ path: url.pathname, method });
    requestUrls.push(`${url.pathname}${url.search}`);

    if (url.pathname === "/job-search/configs" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET")
      return Response.json(storedJobs);
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json({
        has_brightdata_api_key: true,
        brightdata_api_key_preview: "test...key",
      });
    }
    if (url.pathname === "/job-search/run" && method === "POST") {
      runBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      const job = importedJobData({
        id: "indeed-example",
        title: "Junior Data Engineer",
        source: "indeed",
      });
      storedJobs = [{ id: job.id, data: job }];
      return Response.json({
        status: "completed",
        jobsFound: 1,
        jobsAdded: 1,
        sourceErrors: {},
        warning: null,
      });
    }
    if (url.pathname === "/jobs/ai-match/run" && method === "POST") {
      return Response.json(
        { detail: "AI match disabled in test" },
        { status: 403 },
      );
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Search vacancies" }),
  );
  const linkedinSource = screen.getByRole("button", {
    name: "Include LinkedIn in search",
  });
  const indeedSource = screen.getByRole("button", {
    name: "Include Indeed in search",
  });
  const jobsChSource = screen.getByRole("button", {
    name: "Include jobs.ch in search",
  });
  expect(linkedinSource).toHaveAttribute("aria-pressed", "true");
  expect(indeedSource).toHaveAttribute("aria-pressed", "false");
  expect(jobsChSource).toHaveAttribute("aria-pressed", "false");

  fireEvent.click(screen.getByRole("button", { name: "Configure Indeed" }));
  expect(screen.getByText("2. Configure Indeed")).toBeInTheDocument();
  expect(indeedSource).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(indeedSource);
  fireEvent.click(jobsChSource);
  expect(linkedinSource).toHaveAttribute("aria-pressed", "true");
  expect(indeedSource).toHaveAttribute("aria-pressed", "true");
  expect(jobsChSource).toHaveAttribute("aria-pressed", "true");
  expect(
    screen.getByText("These query fields belong only to Indeed."),
  ).toBeInTheDocument();
  fireEvent.change(
    screen.getByPlaceholderText(
      "e.g. Product Designer, UX Designer, Design System",
    ),
    { target: { value: "platform" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Start search" }));

  await waitFor(() => {
    expect(requests).toContainEqual({
      path: "/job-search/run",
      method: "POST",
    });
  });
  expect(runBodies[0]).toMatchObject({
    sources: ["linkedin", "indeed", "jobs_ch"],
    aiAnalysisEnabled: true,
    config: {
      filters: {
        schemaVersion: 2,
        screening: {
          enabled: true,
          targetRoles: ["platform"],
        },
        search: {
          keywords: "platform",
        },
      },
    },
  });
  expect(runBodies[0]).toHaveProperty("config");
  expect(
    (
      (runBodies[0].config as Record<string, unknown>).filters as {
        search: Record<string, unknown>;
      }
    ).search,
  ).not.toHaveProperty("sources");
  expect(
    await screen.findByText(
      "Added 1 of 1 vacancies from LinkedIn + Indeed + jobs.ch",
    ),
  ).toBeInTheDocument();
  expect(
    requests.filter(
      (request) => request.path === "/jobs" && request.method === "GET",
    ).length,
  ).toBeGreaterThanOrEqual(2);
  expect(
    screen.getAllByRole("img", { name: "Data Engineering role · Indeed" }),
  ).toHaveLength(2);
  expect(screen.getAllByText("Source: Indeed")).toHaveLength(2);

  fireEvent.click(screen.getByRole("button", { name: "Analysis" }));
  const analysisMenu = screen.getByRole("menu", { name: "Bulk AI analysis" });
  expect(
    within(analysisMenu).getByRole("menuitem", {
      name: /Vacancies added in the last 24 hours/,
    }),
  ).toBeEnabled();
  fireEvent.click(
    within(analysisMenu).getByRole("menuitem", {
      name: /Vacancies without current analysis/,
    }),
  );
  await waitFor(() =>
    expect(requestUrls).toContain("/jobs/ai-match/run?force=true"),
  );
});

it("collects current AI consent and resumes the requested 24-hour analysis", async () => {
  window.history.replaceState(null, "", "#jobs");
  const recentJob = importedJobData({
    id: "linkedin-recent-consent-job",
    title: "Data Engineer",
  });
  window.localStorage.setItem(
    "tasko.importedJobs.v1",
    JSON.stringify([recentJob]),
  );

  let aiMatchAttempts = 0;
  const consentRequests: Array<Record<string, unknown>> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET")
      return Response.json([{ id: recentJob.id, data: recentJob }]);
    if (url.pathname === "/jobs" && method === "PUT")
      return Response.json([{ id: recentJob.id, data: recentJob }]);
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET")
      return Response.json(configuredAppSettings);
    if (url.pathname === "/jobs/ai-match/run" && method === "POST") {
      aiMatchAttempts += 1;
      if (aiMatchAttempts === 1) {
        return Response.json(
          {
            detail: {
              code: "ai_consent_required",
              message: "Current AI data-processing consent is required",
              requiredVersion: "2026-07-18.v2",
            },
          },
          { status: 403 },
        );
      }
      return Response.json({
        runId: "consented-match-run",
        status: "completed",
        total: 1,
        processed: 1,
        updatedJobs: [],
      });
    }
    if (url.pathname === "/privacy/ai-consent" && method === "GET") {
      return Response.json({
        providerName: "OpenAI via OpenClaw/Codex",
        currentBackend: "openclaw_codex",
        currentConsentVersion: "2026-07-18.v2",
        consentVersion: null,
        consentBackend: null,
        consentedAt: null,
        hasCurrentConsent: false,
        retentionDays: 30,
        lastAiActivityAt: null,
        aiDataExpiresAt: null,
      });
    }
    if (url.pathname === "/privacy/ai-consent" && method === "PUT") {
      const request = JSON.parse(String(init?.body)) as Record<string, unknown>;
      consentRequests.push(request);
      return Response.json({
        providerName: "OpenAI via OpenClaw/Codex",
        currentBackend: "openclaw_codex",
        currentConsentVersion: "2026-07-18.v2",
        consentVersion: request.version,
        consentBackend: request.backend,
        consentedAt: "2026-08-12T10:00:00.000Z",
        hasCurrentConsent: true,
        retentionDays: request.retentionDays,
        lastAiActivityAt: null,
        aiDataExpiresAt: null,
      });
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  expect(await screen.findByText("1 jobs found")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Analysis" }));
  fireEvent.click(
    within(screen.getByRole("menu", { name: "Bulk AI analysis" })).getByRole(
      "menuitem",
      { name: /Vacancies added in the last 24 hours/ },
    ),
  );

  const consentDialog = await screen.findByRole("dialog", {
    name: "Analyze vacancies with OpenAI via OpenClaw/Codex",
  });
  expect(
    screen.queryByText("Current AI data-processing consent is required"),
  ).not.toBeInTheDocument();
  fireEvent.click(within(consentDialog).getByRole("checkbox"));
  fireEvent.click(
    within(consentDialog).getByRole("button", { name: "Continue to AI" }),
  );

  await waitFor(() => expect(aiMatchAttempts).toBe(2));
  expect(consentRequests).toEqual([
    {
      version: "2026-07-18.v2",
      backend: "openclaw_codex",
      retentionDays: 30,
    },
  ]);
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", {
        name: "Analyze vacancies with OpenAI via OpenClaw/Codex",
      }),
    ).not.toBeInTheDocument(),
  );
});

it("does not re-add a vacancy whose deleted id was synchronized with the server", async () => {
  window.history.replaceState(null, "", "#jobs");
  const dismissedId = "linkedin-https-www-linkedin-com-jobs-view-123";
  window.localStorage.setItem(
    "tasko.deletedJobIds.v1",
    JSON.stringify([dismissedId]),
  );
  const requests: Array<{ path: string; method: string }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    requests.push({ path: url.pathname, method });

    if (url.pathname === "/job-search/configs" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs/dismissed-ids" && method === "PUT") {
      return Response.json([dismissedId]);
    }
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json({
        has_brightdata_api_key: true,
        brightdata_api_key_preview: "test...key",
      });
    }
    if (url.pathname === "/job-search/run" && method === "POST") {
      return Response.json({
        status: "completed",
        jobsFound: 1,
        jobsAdded: 0,
        sourceErrors: {},
        warning: null,
      });
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  await waitFor(() => {
    expect(requests).toContainEqual({
      path: "/jobs/dismissed-ids",
      method: "PUT",
    });
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Search vacancies" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Start search" }));

  expect(
    await screen.findByText(
      "Found 1 vacancies; all were already saved or deleted",
    ),
  ).toBeInTheDocument();
  expect(requests).toContainEqual({ path: "/job-search/run", method: "POST" });
  expect(requests).not.toContainEqual({ path: "/jobs", method: "PUT" });
  expect(requests).not.toContainEqual({
    path: "/jobs/ai-match/run",
    method: "POST",
  });
});

it("loads a server config and refreshes backend-persisted search results", async () => {
  window.history.replaceState(null, "", "#jobs");
  const runBodies: Array<Record<string, unknown>> = [];
  let storedJobs: Array<{ id: string; data: unknown }> = [];
  const entryItConfig = {
    id: "entry-it",
    name: "Entry IT",
    createdAt: "2026-07-21T00:00:00.000Z",
    updatedAt: "2026-07-21T00:00:00.000Z",
    filters: {
      schemaVersion: 2,
      search: {
        sources: ["linkedin"],
        keywords: "entry IT",
        location: "Zurich, Switzerland",
        remote: "Any",
        experienceLevel: "Any",
        jobType: "Any",
        datePosted: "Past 24 hours",
        resultsLimit: 50,
        country: "Switzerland",
        deduplicate: true,
        searchName: "Entry IT",
        folder: "",
      },
      screening: {
        enabled: true,
        targetRoles: ["entry IT"],
        excludedRoles: ["Cashier"],
        allowedSeniority: ["entry", "junior"],
        excludedSeniority: ["senior"],
        hardRules: [],
      },
    },
  };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET") {
      return Response.json([entryItConfig]);
    }
    if (url.pathname === "/job-search/source-configs" && method === "GET") {
      return Response.json([
        {
          id: "entry-it-linkedin",
          name: "Entry IT · LinkedIn",
          configId: "entry-it",
          source: "linkedin",
          filters: entryItConfig.filters.search,
          createdAt: "2026-07-21T00:00:00.000Z",
          updatedAt: "2026-07-21T00:00:00.000Z",
        },
      ]);
    }
    if (url.pathname === "/job-search/presets" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/jobs" && method === "GET")
      return Response.json(storedJobs);
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json({
        has_brightdata_api_key: true,
        brightdata_api_key_preview: "test...key",
      });
    }
    if (url.pathname === "/job-search/run" && method === "POST") {
      runBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      const junior = importedJobData({
        id: "linkedin-junior-python",
        title: "Junior Python Developer",
      });
      const embedded = importedJobData({
        id: "linkedin-werkstudent-embedded",
        title: "Werkstudent Embedded-Software-Entwicklung",
      });
      storedJobs = [
        { id: junior.id, data: junior },
        { id: embedded.id, data: embedded },
      ];
      return Response.json({
        status: "completed",
        jobsFound: 2,
        jobsAdded: 2,
        sourceErrors: {},
        warning: null,
      });
    }

    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Search vacancies" }),
  );
  fireEvent.change(await screen.findByLabelText("Existing configs"), {
    target: { value: "entry-it" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Start search" }));

  expect(
    await screen.findByText("Added 2 of 2 vacancies from LinkedIn"),
  ).toBeInTheDocument();
  expect(runBodies[0]).toMatchObject({
    sources: ["linkedin"],
    configId: "entry-it",
    sourceConfigIds: { linkedin: "entry-it-linkedin" },
  });
  expect(runBodies[0]).not.toHaveProperty("config");
  expect(screen.getAllByText("Junior Python Developer").length).toBeGreaterThan(
    0,
  );
  expect(
    screen.getAllByText("Werkstudent Embedded-Software-Entwicklung").length,
  ).toBeGreaterThan(0);
});

it("loads a run preset with a separate query config for every aggregator", async () => {
  window.history.replaceState(null, "", "#jobs");
  const runBodies: Array<Record<string, unknown>> = [];
  const entryItConfig = {
    id: "entry-it",
    name: "Entry IT",
    createdAt: "2026-07-21T00:00:00.000Z",
    updatedAt: "2026-07-21T00:00:00.000Z",
    filters: {
      schemaVersion: 2,
      search: { keywords: "common company query", resultsLimit: 50 },
      screening: { enabled: true, targetRoles: ["Entry IT"] },
    },
  };
  const sourceConfigIds = {
    linkedin: "entry-it-linkedin",
    indeed: "entry-it-indeed",
    jobs_ch: "entry-it-jobs-ch",
  };
  const sourceConfigs = Object.entries(sourceConfigIds).map(([source, id]) => ({
    id,
    name: `Entry IT · ${source}`,
    configId: "entry-it",
    source,
    filters: { keywords: `${source} query`, resultsLimit: 50 },
    createdAt: "2026-07-21T00:00:00.000Z",
    updatedAt: "2026-07-21T00:00:00.000Z",
  }));
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";
    if (url.pathname === "/job-search/configs" && method === "GET") {
      return Response.json([entryItConfig]);
    }
    if (url.pathname === "/job-search/source-configs" && method === "GET") {
      return Response.json(sourceConfigs);
    }
    if (url.pathname === "/job-search/presets" && method === "GET") {
      return Response.json([
        {
          id: "entry-it-all-sources",
          name: "Entry IT · all sources",
          configId: "entry-it",
          sources: ["linkedin", "indeed", "jobs_ch"],
          sourceConfigIds,
          createdAt: "2026-07-21T00:00:00.000Z",
          updatedAt: "2026-07-21T00:00:00.000Z",
        },
      ]);
    }
    if (url.pathname === "/job-search/run" && method === "POST") {
      runBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return Response.json({
        status: "completed",
        jobsFound: 0,
        jobsAdded: 0,
        sourceErrors: {},
        warning: null,
      });
    }
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/applications" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/applications/events" && method === "GET")
      return Response.json([]);
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json({ has_brightdata_api_key: true });
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Search vacancies" }),
  );
  fireEvent.change(await screen.findByLabelText("Saved run preset"), {
    target: { value: "entry-it-all-sources" },
  });

  expect(screen.getByLabelText("LinkedIn query config")).toHaveValue(
    "entry-it-linkedin",
  );
  expect(
    screen.getByPlaceholderText(
      "e.g. Product Designer, UX Designer, Design System",
    ),
  ).toHaveValue("linkedin query");
  fireEvent.click(screen.getByRole("button", { name: "Configure Indeed" }));
  expect(screen.getByLabelText("Indeed query config")).toHaveValue(
    "entry-it-indeed",
  );
  expect(
    screen.getByPlaceholderText(
      "e.g. Product Designer, UX Designer, Design System",
    ),
  ).toHaveValue("indeed query");
  fireEvent.click(screen.getByRole("button", { name: "Configure jobs.ch" }));
  expect(screen.getByLabelText("jobs.ch query config")).toHaveValue(
    "entry-it-jobs-ch",
  );
  fireEvent.change(screen.getByLabelText("jobs.ch query config"), {
    target: { value: "" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Start search" }));
  expect(
    await screen.findByText("Select a query config for jobs.ch"),
  ).toBeInTheDocument();
  expect(runBodies).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("jobs.ch query config"), {
    target: { value: "entry-it-jobs-ch" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Start search" }));

  expect(
    await screen.findByText(
      "No vacancies returned from LinkedIn + Indeed + jobs.ch",
    ),
  ).toBeInTheDocument();
  expect(runBodies[0]).toMatchObject({
    configId: "entry-it",
    sources: ["linkedin", "indeed", "jobs_ch"],
    sourceConfigIds,
  });
});

it("imports legacy local search configs to the server only once", async () => {
  window.history.replaceState(null, "", "#jobs");
  window.localStorage.setItem(
    "tasko.parserSearchConfigs.v2",
    JSON.stringify([
      {
        id: "legacy-zurich",
        name: "Legacy Zurich",
        updatedAt: "2026-07-20T09:00:00.000Z",
        form: {
          parsers: ["linkedin", "indeed"],
          keywords: "Platform Engineer",
          location: "Zurich",
          remote: "Any",
          experienceLevel: "Any",
          jobType: "Full-time",
          datePosted: "Past week",
          resultsLimit: "25",
          country: "Switzerland",
          deduplicate: true,
          searchName: "Legacy Zurich",
          folder: "",
        },
      },
    ]),
  );
  const configWrites: Array<Record<string, unknown>> = [];
  const serverConfigs: Array<Record<string, unknown>> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET") {
      return Response.json(serverConfigs);
    }
    if (url.pathname === "/job-search/configs" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      configWrites.push(body);
      const saved = {
        id: "server-config-1",
        ...body,
        createdAt: "2026-07-23T10:00:00.000Z",
        updatedAt: "2026-07-23T10:00:00.000Z",
      };
      serverConfigs.push(saved);
      return Response.json(saved, { status: 201 });
    }
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs/dismissed-ids" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/applications" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/applications/events" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json(configuredAppSettings);
    }
    if (
      (url.pathname === "/applications" ||
        url.pathname === "/applications/events") &&
      method === "PUT"
    ) {
      return Response.json([]);
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  const firstRender = render(<HomePage />);
  await waitFor(() => expect(configWrites).toHaveLength(1));
  expect(configWrites[0]).toMatchObject({
    name: "Legacy Zurich",
    filters: {
      schemaVersion: 2,
      search: {
        keywords: "Platform Engineer",
        location: "Zurich",
        resultsLimit: 25,
        deduplicate: true,
      },
      screening: {
        enabled: true,
        targetRoles: ["Platform Engineer"],
      },
    },
  });
  expect(
    (configWrites[0].filters as Record<string, unknown>).search as Record<
      string,
      unknown
    >,
  ).not.toHaveProperty("sources");
  expect(
    window.localStorage.getItem("tasko.parserSearchConfigs.v2"),
  ).toBeNull();

  firstRender.unmount();
  render(<HomePage />);
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.filter(([input, init]) => {
        const requestUrl =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        return (
          new URL(requestUrl, "http://localhost").pathname ===
            "/job-search/configs" && (init?.method ?? "GET") === "GET"
        );
      }).length,
    ).toBeGreaterThanOrEqual(2);
  });
  expect(configWrites).toHaveLength(1);
});

it("saves and deletes manual-search configs through the API", async () => {
  window.history.replaceState(null, "", "#jobs");
  const configRequests: Array<{
    path: string;
    method: string;
    body?: Record<string, unknown>;
  }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/job-search/configs" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      configRequests.push({ path: url.pathname, method, body });
      return Response.json(
        {
          id: "manual-config-1",
          ...body,
          createdAt: "2026-07-23T10:00:00.000Z",
          updatedAt: "2026-07-23T10:00:00.000Z",
        },
        { status: 201 },
      );
    }
    if (
      url.pathname === "/job-search/configs/manual-config-1" &&
      method === "DELETE"
    ) {
      configRequests.push({ path: url.pathname, method });
      return new Response(null, { status: 204 });
    }
    if (url.pathname === "/jobs" && method === "GET") return Response.json([]);
    if (url.pathname === "/jobs/dismissed-ids" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/applications" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/applications/events" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json(configuredAppSettings);
    }
    if (
      (url.pathname === "/applications" ||
        url.pathname === "/applications/events") &&
      method === "PUT"
    ) {
      return Response.json([]);
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Search vacancies" }),
  );
  fireEvent.change(
    screen.getByPlaceholderText("e.g. Product Designer Remote Jobs"),
    {
      target: { value: "Remote platform roles" },
    },
  );
  fireEvent.change(
    screen.getByPlaceholderText(
      "e.g. Product Designer, UX Designer, Design System",
    ),
    {
      target: { value: "Platform Engineer" },
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Save config" }));

  expect(
    await screen.findByText("Saved config: Remote platform roles"),
  ).toBeInTheDocument();
  expect(configRequests[0]).toMatchObject({
    path: "/job-search/configs",
    method: "POST",
    body: {
      name: "Remote platform roles",
      filters: {
        schemaVersion: 2,
        search: {
          keywords: "Platform Engineer",
          resultsLimit: 10,
          deduplicate: true,
        },
        screening: {
          enabled: true,
          targetRoles: ["Platform Engineer"],
        },
      },
    },
  });
  expect(
    (
      (configRequests[0].body as Record<string, unknown>).filters as Record<
        string,
        unknown
      >
    ).search as Record<string, unknown>,
  ).not.toHaveProperty("sources");

  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(
    await screen.findByText("Deleted config: Remote platform roles"),
  ).toBeInTheDocument();
  expect(configRequests[1]).toEqual({
    path: "/job-search/configs/manual-config-1",
    method: "DELETE",
  });
  expect(
    window.localStorage.getItem("tasko.parserSearchConfigs.v2"),
  ).toBeNull();
});

it("shows direct-company vacancies with their company logos", async () => {
  window.history.replaceState(null, "", "#jobs");
  const configWrites: Array<Record<string, unknown>> = [];
  const runRequests: Array<Record<string, unknown>> = [];
  let storedJobs: Array<{ id: string; data: unknown }> = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(requestUrl, "http://localhost");
    const method = init?.method ?? "GET";

    if (url.pathname === "/job-search/configs" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/job-search/configs" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      configWrites.push(body);
      return Response.json(
        {
          id: "direct-companies-config",
          ...body,
          createdAt: "2026-08-01T10:00:00.000Z",
          updatedAt: "2026-08-01T10:00:00.000Z",
        },
        { status: 201 },
      );
    }
    if (url.pathname === "/job-search/run" && method === "POST") {
      runRequests.push(
        JSON.parse(String(init?.body)) as Record<string, unknown>,
      );
      const diePostJob = importedJobData({
        id: "die_post-platform-engineer",
        title: "Platform Engineer at Die Post",
        source: "die_post",
      });
      const migrosBankJob = importedJobData({
        id: "migros_bank-devsecops-engineer",
        title: "DevSecOps Engineer at Migros Bank",
        source: "migros_bank",
      });
      const raiffeisenJob = importedJobData({
        id: "raiffeisen-platform-engineer",
        title: "Platform Engineer at Raiffeisen",
        source: "raiffeisen",
      });
      const bundesverwaltungJob = importedJobData({
        id: "bundesverwaltung-platform-engineer",
        title: "Platform Engineer at Bundesverwaltung",
        source: "bundesverwaltung",
      });
      const axaSchweizJob = importedJobData({
        id: "axa_schweiz-platform-engineer",
        title: "Platform Engineer at AXA Schweiz",
        source: "axa_schweiz",
      });
      const sunriseJob = importedJobData({
        id: "sunrise-platform-engineer",
        title: "Platform Engineer at Sunrise",
        source: "sunrise",
      });
      const issJob = importedJobData({
        id: "iss-facility-engineer",
        title: "Facility Engineer at ISS Schweiz",
        source: "iss",
      });
      const accentureJob = importedJobData({
        id: "accenture-cloud-platform-engineer",
        title: "Cloud Platform Engineer at Accenture",
        source: "accenture",
      });
      const csemJob = importedJobData({
        id: "csem-senior-software-engineer",
        title: "Senior Software Engineer at CSEM",
        source: "csem",
      });
      const deloitteJob = importedJobData({
        id: "deloitte-assistant-manager",
        title: "Assistant Manager at Deloitte",
        source: "deloitte",
      });
      const zuercherKantonalbankJob = importedJobData({
        id: "zuercher_kantonalbank-devops-engineer",
        title: "DevOps Engineer at Zürcher Kantonalbank",
        source: "zuercher_kantonalbank",
      });
      const flughafenZuerichJob = importedJobData({
        id: "flughafen_zuerich-system-engineer",
        title: "System Engineer at Flughafen Zürich",
        source: "flughafen_zuerich",
      });
      const ubsStudentsGraduatesJob = importedJobData({
        id: "ubs_students_graduates-internship",
        title: "Off-cycle Internship at UBS",
        source: "ubs_students_graduates",
      });
      const abbSwitzerlandJob = importedJobData({
        id: "abb_switzerland-service-engineer",
        title: "Service Engineer at ABB",
        source: "abb_switzerland",
      });
      const huaweiSwitzerlandJob = importedJobData({
        id: "huawei_switzerland-research-engineer",
        title: "Research Engineer at Huawei",
        source: "huawei_switzerland",
      });
      const bdoSwitzerlandJob = importedJobData({
        id: "bdo_switzerland-abacus-consultant",
        title: "Abacus Consultant at BDO",
        source: "bdo_switzerland",
      });
      const endressHauserSwitzerlandJob = importedJobData({
        id: "endress_hauser_switzerland-41541-en_US",
        title: "Application Engineer at Endress+Hauser",
        source: "endress_hauser_switzerland",
      });
      const microsoftSwitzerlandJob = importedJobData({
        id: "microsoft_switzerland-1970393556942270",
        title: "Software Engineer II at Microsoft",
        source: "microsoft_switzerland",
      });
      const sapSwitzerlandJob = importedJobData({
        id: "sap_switzerland-1392727333",
        title: "Account Executive at SAP",
        source: "sap_switzerland",
      });
      const sPeersJob = importedJobData({
        id: "s_peers-48262",
        title: "Senior Data Engineer at s-peers",
        source: "s_peers",
      });
      const mobiliarJob = importedJobData({
        id: "mobiliar-1798",
        title: "Corporate Resilience Manager at Mobiliar",
        source: "mobiliar",
      });
      const emmiJob = importedJobData({
        id: "emmi-10142500",
        title: "Lead Organizational Development at Emmi",
        source: "emmi",
      });
      const sulzerSwitzerlandJob = importedJobData({
        id: "sulzer_switzerland-jr103919",
        title: "Head of Product Marketing at Sulzer",
        source: "sulzer_switzerland",
      });
      const siegfriedJob = importedJobData({
        id: "siegfried-r26-655",
        title: "Head Maintenance at Siegfried",
        source: "siegfried",
      });
      const switchJob = importedJobData({
        id: "switch-557",
        title: "Technical Documentation Specialist at Switch",
        source: "switch",
      });
      const huberSuhnerSwitzerlandJob = importedJobData({
        id: "huber_suhner_switzerland-7806",
        title: "Corporate Controller at Huber+Suhner",
        source: "huber_suhner_switzerland",
      });
      const stadlerItSwitzerlandJob = importedJobData({
        id: "stadler_it_switzerland-10133279",
        title: "DevOps & Integration Engineer at Stadler",
        source: "stadler_it_switzerland",
      });
      const ebpSwitzerlandJob = importedJobData({
        id: "ebp_switzerland-b913f9ef-1bdc-4824-8b46-ea0607c12c58",
        title: "Junior Projektleiter/in at EBP",
        source: "ebp_switzerland",
      });
      const ruagSwitzerlandJob = importedJobData({
        id: "ruag_switzerland-24e02ed3-4dc6-4358-a9f4-9383b380371b",
        title: "Helikoptermechaniker EC-635 at RUAG",
        source: "ruag_switzerland",
      });
      const cyberlinkJob = importedJobData({
        id: "cyberlink-spontanbewerbung",
        title: "Spontanbewerbung at Cyberlink",
        source: "cyberlink",
      });
      const ergonJob = importedJobData({
        id: "ergon-2587674",
        title: "Senior Fullstack Software Engineer at Ergon",
        source: "ergon",
      });
      const logobjectJob = importedJobData({
        id: "logobject-wirtschaftsinformatiker-software-entwicklung-m-w-d-1",
        title: "Wirtschaftsinformatiker Software Entwicklung at LogObject",
        source: "logobject",
      });
      const ti8mSwitzerlandJob = importedJobData({
        id: "ti8m_switzerland-cc7debd9-6eea-40f0-9c48-6a8152ca5227",
        title: "Senior Business Analyst at ti&m",
        source: "ti8m_switzerland",
      });
      const novartisSwitzerlandJob = importedJobData({
        id: "novartis_switzerland-req-10084379",
        title: "AI Scientist at Novartis",
        source: "novartis_switzerland",
      });
      const pictetSwitzerlandJob = importedJobData({
        id: "pictet_switzerland-124439",
        title: "Group Tax Expert at Pictet",
        source: "pictet_switzerland",
      });
      const swissReJob = importedJobData({
        id: "swiss_re-1412388733",
        title: "Senior Security Analyst at Swiss Re",
        source: "swiss_re",
      });
      const baloiseJob = importedJobData({
        id: "baloise-76a59d77-7553-4683-8e4c-961a2bc0e56f",
        title: "Security Engineer at Baloise",
        source: "baloise",
      });
      const elcaJob = importedJobData({
        id: "elca-2790",
        title: "Business Development Manager at ELCA",
        source: "elca",
      });
      const aveniqJob = importedJobData({
        id: "aveniq-2672332",
        title: "Technical Account Manager at Aveniq",
        source: "aveniq",
      });
      const mimacomJob = importedJobData({
        id: "mimacom-senior-java-spring-engineer-80-100-mfd",
        title: "Senior Java Engineer at Mimacom",
        source: "mimacom",
      });
      const unit8SwitzerlandJob = importedJobData({
        id: "unit8_switzerland-DA88B40606",
        title: "Palantir Foundry Engineer at Unit8",
        source: "unit8_switzerland",
      });
      const axpoSwitzerlandJob = importedJobData({
        id: "axpo_switzerland-8196100",
        title: "Mitarbeiter Betriebsdienst at Axpo",
        source: "axpo_switzerland",
      });
      const ringierJob = importedJobData({
        id: "ringier-10136337",
        title: "IT Identity Engineer at Ringier",
        source: "ringier",
      });
      const msdJob = importedJobData({
        id: "msd-r409018",
        title: "HR Intern Switzerland at MSD",
        source: "msd",
      });
      const srgSsrJob = importedJobData({
        id: "srg_ssr-ba2e34a8-f6d3-4190-9557-30f463c1420d",
        title: "Prozessanalyst:in at SRG SSR",
        source: "srg_ssr",
      });
      const ibmJob = importedJobData({
        id: "ibm-125336",
        title: "Storage Sales Support at IBM",
        source: "ibm",
      });
      const googleJob = importedJobData({
        id: "google-106855447041843910",
        title: "Software Engineer at Google",
        source: "google",
      });
      const buhlerSwitzerlandJob = importedJobData({
        id: "buhler_switzerland-10140259",
        title: "Case Manager:in at Bühler",
        source: "buhler_switzerland",
      });
      const oracleSwitzerlandJob = importedJobData({
        id: "oracle_switzerland-335070",
        title: "Cloud Engineer at Oracle",
        source: "oracle_switzerland",
      });
      const adnovumJob = importedJobData({
        id: "adnovum-1164795855",
        title: "Senior Solution Architect at Adnovum",
        source: "adnovum",
      });
      const eySwitzerlandJob = importedJobData({
        id: "ey_switzerland-technology-consultant",
        title: "Technology Consultant at EY",
        source: "ey_switzerland",
      });
      const ethZurichJob = importedJobData({
        id: "eth_zurich-platform-engineer",
        title: "Platform Engineer at ETH Zürich",
        source: "eth_zurich",
      });
      const siemensSwitzerlandJob = importedJobData({
        id: "siemens_switzerland-automation-engineer",
        title: "Automation Engineer at Siemens",
        source: "siemens_switzerland",
      });
      const kpmgSwitzerlandJob = importedJobData({
        id: "kpmg_switzerland-technology-consultant",
        title: "Technology Consultant at KPMG",
        source: "kpmg_switzerland",
      });
      const swissgridJob = importedJobData({
        id: "swissgrid-cloud-engineer",
        title: "Cloud Engineer at Swissgrid",
        source: "swissgrid",
      });
      const suvaJob = importedJobData({
        id: "suva-7878",
        title: "Business Analyst at Suva",
        source: "suva",
      });
      const aoFoundationJob = importedJobData({
        id: "ao_foundation-1419823633",
        title: "Senior IT Security Engineer at AO Foundation",
        source: "ao_foundation",
      });
      const skyguideJob = importedJobData({
        id: "skyguide-1399690633",
        title: "Network Architect at Skyguide",
        source: "skyguide",
      });
      const rocheSwitzerlandJob = importedJobData({
        id: "roche_switzerland-202603-108151",
        title: "Computational Scientist at Roche",
        source: "roche_switzerland",
      });
      const logitechSwitzerlandJob = importedJobData({
        id: "logitech_switzerland-147622",
        title: "Finance Operations Director at Logitech",
        source: "logitech_switzerland",
      });
      const swatchGroupJob = importedJobData({
        id: "swatch_group-32458",
        title: "IT Support Specialist at Swatch Group",
        source: "swatch_group",
      });
      const amazonSwitzerlandJob = importedJobData({
        id: "amazon_switzerland-10496693",
        title: "Partner Development Manager at Amazon",
        source: "amazon_switzerland",
      });
      const cognizantSwitzerlandJob = importedJobData({
        id: "cognizant_switzerland-47495",
        title: "Onsite Support Services Engineer at Cognizant",
        source: "cognizant_switzerland",
      });
      const fisbaJob = importedJobData({
        id: "fisba-einkaufer-100-mw",
        title: "Einkäufer at FISBA",
        source: "fisba",
      });
      const gritecJob = importedJobData({
        id: "gritec-63f65b7f-9508-402d-aab7-5ff491cb5f0f",
        title: "Software Engineer at GRITEC",
        source: "gritec",
      });
      const helblingJob = importedJobData({
        id: "helbling-1167",
        title: "Embedded Software Engineer at Helbling",
        source: "helbling",
      });
      const maerkiBaumannJob = importedJobData({
        id: "maerki_baumann-78216",
        title: "Mitarbeiter/in Kundendokumentation at Maerki Baumann",
        source: "maerki_baumann",
      });
      const electrosuisseJob = importedJobData({
        id: "electrosuisse-80275",
        title: "IT Helpdesk Support at Electrosuisse",
        source: "electrosuisse",
      });
      const deteconSwitzerlandJob = importedJobData({
        id: "detecon_switzerland-student-consultant-applied-agentic-ai-entwicklung-all-genders",
        title: "Student Consultant Applied AI at Detecon",
        source: "detecon_switzerland",
      });
      const lufthansaGroupSwitzerlandJob = importedJobData({
        id: "lufthansa_group_switzerland-134020",
        title: "Data & AI Internship at SWISS",
        source: "lufthansa_group_switzerland",
      });
      const adessoSwitzerlandJob = importedJobData({
        id: "adesso_switzerland-2956",
        title: "Senior Consultant Business Automation at Adesso",
        source: "adesso_switzerland",
      });
      const cudosJob = importedJobData({
        id: "cudos-senior-software-engineer-c-sharp",
        title: "Senior Software Engineer C# at Cudos",
        source: "cudos",
      });
      const eraneosSwitzerlandJob = importedJobData({
        id: "eraneos_switzerland-jr100169",
        title: "Cybersecurity Consultant at Eraneos",
        source: "eraneos_switzerland",
      });
      const erniSwitzerlandJob = importedJobData({
        id: "erni_switzerland-7852745",
        title: "Rust Software Engineer at ERNI",
        source: "erni_switzerland",
      });
      const bachemJob = importedJobData({
        id: "bachem-1425152933",
        title: "Batchdocument Reviewer at Bachem",
        source: "bachem",
      });
      const georgFischerSwitzerlandJob = importedJobData({
        id: "georg_fischer_switzerland-jr10784",
        title: "FormenmonteurIn at Georg Fischer",
        source: "georg_fischer_switzerland",
      });
      const alsoJob = importedJobData({
        id: "also-296512",
        title: "Group Reporting Specialist at ALSO",
        source: "also",
      });
      const bedagJob = importedJobData({
        id: "bedag-1008",
        title: "Senior ICT-Controller at Bedag",
        source: "bedag",
      });
      const nexploreJob = importedJobData({
        id: "nexplore-bcff2b26-bae2-48e2-851d-f39ee1fbcb3d",
        title: "Software Test Engineer at Nexplore",
        source: "nexplore",
      });
      const nttGlobalDataCentersJob = importedJobData({
        id: "ntt_global_data_centers_switzerland-jr101121",
        title: "Litigation & Claims Counsel at NTT Global Data Centers",
        source: "ntt_global_data_centers_switzerland",
      });
      const teradataSwitzerlandJob = importedJobData({
        id: "teradata_switzerland-220353",
        title: "Customer Solution Architect at Teradata",
        source: "teradata_switzerland",
      });
      const swissLifeSwitzerlandJob = importedJobData({
        id: "swiss_life_switzerland-4c6b891f-22b1-494c-ad4e-06a25ede7ef4",
        title:
          "Associate Financial Planner & Relationship Manager at Swiss Life",
        source: "swiss_life_switzerland",
      });
      const sikaSwitzerlandJob = importedJobData({
        id: "sika_switzerland-9c76864a-9d47-46eb-af82-10893fcfc91e",
        title: "Senior Technical Consultant SAP Integration at Sika",
        source: "sika_switzerland",
      });
      const centrisJob = importedJobData({
        id: "centris-1085",
        title: "Fachtester at Centris",
        source: "centris",
      });
      const edorexJob = importedJobData({
        id: "edorex-senior-postgresql-consultant-mwd",
        title: "Senior PostgreSQL Consultant at Edorex",
        source: "edorex",
      });
      const datwylerItInfraJob = importedJobData({
        id: "datwyler_it_infra-432",
        title: "Senior Netzwerk Engineer at Dätwyler IT Infra",
        source: "datwyler_it_infra",
      });
      const infoGuardJob = importedJobData({
        id: "infoguard-incident-responder",
        title: "Incident Responder at InfoGuard",
        source: "infoguard",
      });
      const sixGroupJob = importedJobData({
        id: "six_group-1415188733",
        title: "Head Strategy & Business Development at SIX",
        source: "six_group",
      });
      const comergeJob = importedJobData({
        id: "comerge-software-engineer",
        title: "Senior Software Engineer at Comerge",
        source: "comerge",
      });
      const abraxasJob = importedJobData({
        id: "abraxas-9876",
        title: "Cyber Security Analyst at Abraxas",
        source: "abraxas",
      });
      const akrosJob = importedJobData({
        id: "akros-java-software-engineer-fullstack-zurich",
        title: "Java Software Engineer Fullstack at AKROS",
        source: "akros",
      });
      const ametiqJob = importedJobData({
        id: "ametiq-13617",
        title: "IT-Solution und Security Architekt:in at amétiq",
        source: "ametiq",
      });
      const bsiSoftwareJob = importedJobData({
        id: "bsi_software-software-engineer",
        title: "Software Engineer at BSI Software",
        source: "bsi_software",
      });
      const cmiJob = importedJobData({
        id: "cmi-808dbb0a-dde0-d52b-001d-3dcc84d46f46",
        title: "Lead Scrum Team und Softwareentwickler:in at CMI",
        source: "cmi",
      });
      const egeliInformatikJob = importedJobData({
        id: "egeli_informatik-d77b3af8-f9f7-45b4-9353-d85d64ae37e5",
        title: "Junior ICT System Engineer at EGELI Informatik",
        source: "egeli_informatik",
      });
      const emineoJob = importedJobData({
        id: "emineo-389",
        title: "SAP Accounts Receivable Project Manager at emineo",
        source: "emineo",
      });
      const hostpointJob = importedJobData({
        id: "hostpoint-system-engineer-unix",
        title: "System Engineer Unix at Hostpoint",
        source: "hostpoint",
      });
      const huerlimannInformatikJob = importedJobData({
        id: "huerlimann_informatik-75877",
        title: "Abteilungsleiter/in Technik & Support at Hürlimann Informatik",
        source: "huerlimann_informatik",
      });
      const infosoftJob = importedJobData({
        id: "infosoft-senior-software-engineer-in-net",
        title: "Senior Software Engineer/in .NET at Infosoft",
        source: "infosoft",
      });
      const isolutionsJob = importedJobData({
        id: "isolutions-junior-technical-consultant-digital-workplace",
        title: "Junior Technical Consultant at isolutions",
        source: "isolutions",
      });
      const iwfJob = importedJobData({
        id: "iwf-agile-tester",
        title: "Agile Software Tester / Test Manager at IWF",
        source: "iwf",
      });
      const loewenfelsJob = importedJobData({
        id: "loewenfels-product-owner",
        title: "Product Owner at Löwenfels",
        source: "loewenfels",
      });
      const mSSoftwareEngineeringJob = importedJobData({
        id: "m_s_software_engineering-softwareentwickler",
        title: "Softwareentwickler at M&S",
        source: "m_s_software_engineering",
      });
      const opaccJob = importedJobData({
        id: "opacc-kunden-bedienen-teamleiterin-support",
        title: "TeamleiterIn Support at Opacc",
        source: "opacc",
      });
      const panterJob = importedJobData({
        id: "panter-senior-ai-software-engineer",
        title: "Senior AI Software Engineer at Panter",
        source: "panter",
      });
      const digitalArchitectsZurichJob = importedJobData({
        id: "digital_architects_zurich-job-cicd-consultant",
        title: "CI/CD Engineer & Consultant at Digital Architects Zurich",
        source: "digital_architects_zurich",
      });
      const umbJob = importedJobData({
        id: "umb-744000143231549",
        title: "Senior System Engineer at UMB",
        source: "umb",
      });
      const webtouchJob = importedJobData({
        id: "webtouch-call-agent-in-b2b-outbound",
        title: "Call Agent/in B2B Outbound at Webtouch",
        source: "webtouch",
      });
      const manorJob = importedJobData({
        id: "manor-4041835",
        title: "Polydesigner*in 3D at Manor",
        source: "manor",
      });
      const saltMobileJob = importedJobData({
        id: "salt_mobile-b6bb546f-f060-4a80-98bb-cc5d31f82a54",
        title: "Customer Onboarding & Migration Specialist at Salt Mobile",
        source: "salt_mobile",
      });
      const vzugJob = importedJobData({
        id: "vzug-69b70fad-c7ef-4a6a-932f-db7a00ff345d",
        title: "Professional/Senior Software Engineer at V-ZUG",
        source: "vzug",
      });
      const lindtSpruengliSwitzerlandJob = importedJobData({
        id: "lindt_spruengli_switzerland-jr102591",
        title: "Patissier*in 90% at Lindt & Sprüngli",
        source: "lindt_spruengli_switzerland",
      });
      storedJobs = [
        { id: migrosBankJob.id, data: migrosBankJob },
        { id: diePostJob.id, data: diePostJob },
        { id: raiffeisenJob.id, data: raiffeisenJob },
        { id: bundesverwaltungJob.id, data: bundesverwaltungJob },
        { id: axaSchweizJob.id, data: axaSchweizJob },
        { id: sunriseJob.id, data: sunriseJob },
        { id: issJob.id, data: issJob },
        { id: accentureJob.id, data: accentureJob },
        { id: csemJob.id, data: csemJob },
        { id: deloitteJob.id, data: deloitteJob },
        {
          id: zuercherKantonalbankJob.id,
          data: zuercherKantonalbankJob,
        },
        { id: flughafenZuerichJob.id, data: flughafenZuerichJob },
        { id: ubsStudentsGraduatesJob.id, data: ubsStudentsGraduatesJob },
        { id: abbSwitzerlandJob.id, data: abbSwitzerlandJob },
        { id: huaweiSwitzerlandJob.id, data: huaweiSwitzerlandJob },
        { id: bdoSwitzerlandJob.id, data: bdoSwitzerlandJob },
        {
          id: endressHauserSwitzerlandJob.id,
          data: endressHauserSwitzerlandJob,
        },
        {
          id: microsoftSwitzerlandJob.id,
          data: microsoftSwitzerlandJob,
        },
        { id: sapSwitzerlandJob.id, data: sapSwitzerlandJob },
        { id: sPeersJob.id, data: sPeersJob },
        { id: mobiliarJob.id, data: mobiliarJob },
        { id: emmiJob.id, data: emmiJob },
        { id: sulzerSwitzerlandJob.id, data: sulzerSwitzerlandJob },
        { id: siegfriedJob.id, data: siegfriedJob },
        { id: switchJob.id, data: switchJob },
        {
          id: huberSuhnerSwitzerlandJob.id,
          data: huberSuhnerSwitzerlandJob,
        },
        {
          id: stadlerItSwitzerlandJob.id,
          data: stadlerItSwitzerlandJob,
        },
        { id: ebpSwitzerlandJob.id, data: ebpSwitzerlandJob },
        { id: ruagSwitzerlandJob.id, data: ruagSwitzerlandJob },
        { id: cyberlinkJob.id, data: cyberlinkJob },
        { id: ergonJob.id, data: ergonJob },
        { id: logobjectJob.id, data: logobjectJob },
        { id: ti8mSwitzerlandJob.id, data: ti8mSwitzerlandJob },
        { id: novartisSwitzerlandJob.id, data: novartisSwitzerlandJob },
        { id: pictetSwitzerlandJob.id, data: pictetSwitzerlandJob },
        { id: swissReJob.id, data: swissReJob },
        { id: baloiseJob.id, data: baloiseJob },
        { id: elcaJob.id, data: elcaJob },
        { id: aveniqJob.id, data: aveniqJob },
        { id: mimacomJob.id, data: mimacomJob },
        { id: unit8SwitzerlandJob.id, data: unit8SwitzerlandJob },
        { id: axpoSwitzerlandJob.id, data: axpoSwitzerlandJob },
        { id: ringierJob.id, data: ringierJob },
        { id: msdJob.id, data: msdJob },
        { id: srgSsrJob.id, data: srgSsrJob },
        { id: ibmJob.id, data: ibmJob },
        { id: googleJob.id, data: googleJob },
        { id: buhlerSwitzerlandJob.id, data: buhlerSwitzerlandJob },
        { id: oracleSwitzerlandJob.id, data: oracleSwitzerlandJob },
        { id: adnovumJob.id, data: adnovumJob },
        { id: eySwitzerlandJob.id, data: eySwitzerlandJob },
        { id: ethZurichJob.id, data: ethZurichJob },
        { id: siemensSwitzerlandJob.id, data: siemensSwitzerlandJob },
        { id: kpmgSwitzerlandJob.id, data: kpmgSwitzerlandJob },
        { id: swissgridJob.id, data: swissgridJob },
        { id: suvaJob.id, data: suvaJob },
        { id: aoFoundationJob.id, data: aoFoundationJob },
        { id: skyguideJob.id, data: skyguideJob },
        { id: rocheSwitzerlandJob.id, data: rocheSwitzerlandJob },
        { id: logitechSwitzerlandJob.id, data: logitechSwitzerlandJob },
        { id: swatchGroupJob.id, data: swatchGroupJob },
        { id: amazonSwitzerlandJob.id, data: amazonSwitzerlandJob },
        { id: cognizantSwitzerlandJob.id, data: cognizantSwitzerlandJob },
        { id: fisbaJob.id, data: fisbaJob },
        { id: gritecJob.id, data: gritecJob },
        { id: helblingJob.id, data: helblingJob },
        { id: maerkiBaumannJob.id, data: maerkiBaumannJob },
        { id: electrosuisseJob.id, data: electrosuisseJob },
        { id: deteconSwitzerlandJob.id, data: deteconSwitzerlandJob },
        {
          id: lufthansaGroupSwitzerlandJob.id,
          data: lufthansaGroupSwitzerlandJob,
        },
        { id: adessoSwitzerlandJob.id, data: adessoSwitzerlandJob },
        { id: cudosJob.id, data: cudosJob },
        { id: eraneosSwitzerlandJob.id, data: eraneosSwitzerlandJob },
        { id: erniSwitzerlandJob.id, data: erniSwitzerlandJob },
        { id: bachemJob.id, data: bachemJob },
        {
          id: georgFischerSwitzerlandJob.id,
          data: georgFischerSwitzerlandJob,
        },
        { id: alsoJob.id, data: alsoJob },
        { id: bedagJob.id, data: bedagJob },
        { id: nexploreJob.id, data: nexploreJob },
        {
          id: nttGlobalDataCentersJob.id,
          data: nttGlobalDataCentersJob,
        },
        {
          id: teradataSwitzerlandJob.id,
          data: teradataSwitzerlandJob,
        },
        {
          id: swissLifeSwitzerlandJob.id,
          data: swissLifeSwitzerlandJob,
        },
        {
          id: sikaSwitzerlandJob.id,
          data: sikaSwitzerlandJob,
        },
        { id: centrisJob.id, data: centrisJob },
        { id: edorexJob.id, data: edorexJob },
        { id: datwylerItInfraJob.id, data: datwylerItInfraJob },
        { id: infoGuardJob.id, data: infoGuardJob },
        { id: sixGroupJob.id, data: sixGroupJob },
        { id: comergeJob.id, data: comergeJob },
        { id: abraxasJob.id, data: abraxasJob },
        { id: akrosJob.id, data: akrosJob },
        { id: ametiqJob.id, data: ametiqJob },
        { id: bsiSoftwareJob.id, data: bsiSoftwareJob },
        { id: cmiJob.id, data: cmiJob },
        { id: egeliInformatikJob.id, data: egeliInformatikJob },
        { id: emineoJob.id, data: emineoJob },
        { id: hostpointJob.id, data: hostpointJob },
        { id: huerlimannInformatikJob.id, data: huerlimannInformatikJob },
        { id: infosoftJob.id, data: infosoftJob },
        { id: isolutionsJob.id, data: isolutionsJob },
        { id: iwfJob.id, data: iwfJob },
        { id: loewenfelsJob.id, data: loewenfelsJob },
        {
          id: mSSoftwareEngineeringJob.id,
          data: mSSoftwareEngineeringJob,
        },
        { id: opaccJob.id, data: opaccJob },
        { id: panterJob.id, data: panterJob },
        {
          id: digitalArchitectsZurichJob.id,
          data: digitalArchitectsZurichJob,
        },
        { id: umbJob.id, data: umbJob },
        { id: webtouchJob.id, data: webtouchJob },
        { id: manorJob.id, data: manorJob },
        { id: saltMobileJob.id, data: saltMobileJob },
        { id: vzugJob.id, data: vzugJob },
        {
          id: lindtSpruengliSwitzerlandJob.id,
          data: lindtSpruengliSwitzerlandJob,
        },
      ];
      return Response.json({
        status: "completed",
        jobsFound: 112,
        jobsAdded: 112,
        sourceErrors: {},
        warning: null,
      });
    }
    if (url.pathname === "/jobs" && method === "GET")
      return Response.json(storedJobs);
    if (url.pathname === "/jobs/dismissed-ids" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/applications" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/applications/events" && method === "GET") {
      return Response.json([]);
    }
    if (url.pathname === "/profile" && method === "GET")
      return Response.json({});
    if (url.pathname === "/settings" && method === "GET") {
      return Response.json(configuredAppSettings);
    }
    if (
      (url.pathname === "/applications" ||
        url.pathname === "/applications/events") &&
      method === "PUT"
    ) {
      return Response.json([]);
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<HomePage />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Search vacancies" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Configure Direct Companies" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Include Direct Companies in search" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Include LinkedIn in search" }),
  );

  expect(screen.getByText("Direct company pages")).toBeInTheDocument();
  expect(screen.getByText("SBB CFF FFS")).toBeInTheDocument();
  expect(screen.getByText("Swisscom")).toBeInTheDocument();
  expect(screen.getByText("Galaxus")).toBeInTheDocument();
  expect(screen.getByText("Migros Bank")).toBeInTheDocument();
  expect(screen.getByText("Die Post")).toBeInTheDocument();
  expect(screen.getByText("Raiffeisen")).toBeInTheDocument();
  expect(screen.getByText("Bundesverwaltung")).toBeInTheDocument();
  expect(screen.getByText("AXA Schweiz")).toBeInTheDocument();
  expect(screen.getByText("Sunrise")).toBeInTheDocument();
  expect(screen.getByText("ISS Schweiz")).toBeInTheDocument();
  expect(screen.getByText("Accenture")).toBeInTheDocument();
  expect(screen.getByText("CSEM")).toBeInTheDocument();
  expect(screen.getByText("Deloitte")).toBeInTheDocument();
  expect(screen.getByText("Zürcher Kantonalbank")).toBeInTheDocument();
  expect(screen.getByText("Flughafen Zürich")).toBeInTheDocument();
  expect(screen.getByText("UBS Students & Graduates")).toBeInTheDocument();
  expect(screen.getByText("ABB Schweiz")).toBeInTheDocument();
  expect(screen.getByText("Huawei Switzerland")).toBeInTheDocument();
  expect(screen.getByText("BDO Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Endress+Hauser Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Microsoft Switzerland")).toBeInTheDocument();
  expect(screen.getByText("SAP Switzerland")).toBeInTheDocument();
  expect(screen.getByText("s-peers")).toBeInTheDocument();
  expect(screen.getByText("Mobiliar")).toBeInTheDocument();
  expect(screen.getByText("Emmi")).toBeInTheDocument();
  expect(screen.getByText("Sulzer Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Siegfried")).toBeInTheDocument();
  expect(screen.getByText("Switch")).toBeInTheDocument();
  expect(screen.getByText("Huber+Suhner Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Stadler IT Switzerland")).toBeInTheDocument();
  expect(screen.getByText("EBP Switzerland")).toBeInTheDocument();
  expect(screen.getByText("RUAG Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Cyberlink")).toBeInTheDocument();
  expect(screen.getByText("Ergon")).toBeInTheDocument();
  expect(screen.getByText("LogObject")).toBeInTheDocument();
  expect(screen.getByText("ti&m Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Novartis Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Pictet Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Swiss Re")).toBeInTheDocument();
  expect(screen.getByText("Baloise")).toBeInTheDocument();
  expect(screen.getByText("ELCA")).toBeInTheDocument();
  expect(screen.getByText("Aveniq")).toBeInTheDocument();
  expect(screen.getByText("Mimacom")).toBeInTheDocument();
  expect(screen.getByText("Unit8 Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Axpo Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Ringier")).toBeInTheDocument();
  expect(screen.getByText("MSD")).toBeInTheDocument();
  expect(screen.getByText("SRG SSR")).toBeInTheDocument();
  expect(screen.getByText("IBM")).toBeInTheDocument();
  expect(screen.getByText("Google")).toBeInTheDocument();
  expect(screen.getByText("Bühler Schweiz")).toBeInTheDocument();
  expect(screen.getByText("Oracle Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Adnovum")).toBeInTheDocument();
  expect(screen.getByText("EY Switzerland")).toBeInTheDocument();
  expect(screen.getByText("ETH Zürich")).toBeInTheDocument();
  expect(screen.getByText("Siemens Schweiz")).toBeInTheDocument();
  expect(screen.getByText("KPMG Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Swissgrid")).toBeInTheDocument();
  expect(screen.getByText("Suva")).toBeInTheDocument();
  expect(screen.getByText("AO Foundation")).toBeInTheDocument();
  expect(screen.getByText("Skyguide")).toBeInTheDocument();
  expect(screen.getByText("Roche Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Logitech Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Swatch Group")).toBeInTheDocument();
  expect(screen.getByText("Amazon Switzerland")).toBeInTheDocument();
  expect(
    screen.getByText("Cognizant Technology Solutions AG"),
  ).toBeInTheDocument();
  expect(screen.getByText("FISBA")).toBeInTheDocument();
  expect(screen.getByText("GRITEC")).toBeInTheDocument();
  expect(screen.getByText("Helbling")).toBeInTheDocument();
  expect(screen.getByText("Electrosuisse")).toBeInTheDocument();
  expect(screen.getByText("Detecon Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Lufthansa Group Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Adesso Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Cudos")).toBeInTheDocument();
  expect(screen.getByText("Eraneos Switzerland")).toBeInTheDocument();
  expect(screen.getByText("ERNI Switzerland")).toBeInTheDocument();
  expect(screen.getByText("Abraxas Informatik AG")).toBeInTheDocument();
  expect(screen.getByText("AKROS AG")).toBeInTheDocument();
  expect(screen.getByText("amétiq ag")).toBeInTheDocument();
  expect(screen.getByText("BSI Software")).toBeInTheDocument();
  expect(screen.getByText("CM Informatik AG")).toBeInTheDocument();
  expect(screen.getByText("EGELI Informatik AG")).toBeInTheDocument();
  expect(screen.getByText("emineo AG")).toBeInTheDocument();
  expect(screen.getByText("Hostpoint AG")).toBeInTheDocument();
  expect(screen.getByText("Hürlimann Informatik AG")).toBeInTheDocument();
  expect(screen.getByText("Infosoft Systems AG")).toBeInTheDocument();
  expect(screen.getByText("isolutions AG")).toBeInTheDocument();
  expect(screen.getByText("IWF AG")).toBeInTheDocument();
  expect(screen.getByText("Löwenfels Partner AG")).toBeInTheDocument();
  expect(screen.getByText("M&S Software Engineering AG")).toBeInTheDocument();
  expect(screen.getByText("Opacc Software AG")).toBeInTheDocument();
  expect(screen.getByText("Panter AG")).toBeInTheDocument();
  expect(
    screen.getByText("Digital Architects Zurich GmbH"),
  ).toBeInTheDocument();
  expect(screen.getByText("UMB AG")).toBeInTheDocument();
  expect(screen.getByText("Webtouch GmbH")).toBeInTheDocument();
  expect(screen.getByText("Manor AG")).toBeInTheDocument();
  expect(screen.getByText("Salt Mobile SA")).toBeInTheDocument();
  expect(screen.getByText("V-ZUG AG")).toBeInTheDocument();
  expect(screen.getByText("Lindt & Sprüngli (Schweiz) AG")).toBeInTheDocument();
  expect(
    screen.getByPlaceholderText("Search companies or career pages..."),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Select all" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Add company" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Select all" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /SBB CFF FFS/ }));
  fireEvent.click(screen.getByRole("checkbox", { name: /Swisscom/ }));
  fireEvent.click(screen.getByRole("checkbox", { name: /Galaxus/ }));
  fireEvent.change(
    screen.getByPlaceholderText("e.g. Product Designer Remote Jobs"),
    { target: { value: "Direct companies" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Save config" }));

  expect(
    await screen.findByText("Saved config: Direct companies"),
  ).toBeInTheDocument();
  expect(configWrites).toHaveLength(1);
  expect(configWrites[0]).toMatchObject({
    name: "Direct companies",
    filters: {
      schemaVersion: 2,
    },
  });
  const savedFilters = configWrites[0].filters as Record<string, unknown>;
  const savedSearch = savedFilters.search as Record<string, unknown>;
  expect(savedSearch).not.toHaveProperty("sources");
  expect(savedSearch).not.toHaveProperty("directCompaniesEnabled");
  expect(savedSearch).not.toHaveProperty("directCompanyIds");
  expect(savedSearch).not.toHaveProperty("directCompanies");

  fireEvent.click(screen.getByRole("button", { name: "Start search" }));
  expect(
    await screen.findByText(
      "Added 112 of 112 vacancies from Migros Bank + Die Post + Raiffeisen + Bundesverwaltung + AXA Schweiz + Sunrise + ISS Schweiz + Accenture + CSEM + Deloitte + Zürcher Kantonalbank + Flughafen Zürich + UBS Students & Graduates + ABB Schweiz + Huawei Switzerland + BDO Switzerland + Endress+Hauser Switzerland + Microsoft Switzerland + SAP Switzerland + s-peers + Mobiliar + Emmi + Sulzer Switzerland + Siegfried + Switch + Huber+Suhner Switzerland + Stadler IT Switzerland + EBP Switzerland + RUAG Switzerland + Cyberlink + Ergon + LogObject + ti&m Switzerland + Novartis Switzerland + Pictet Switzerland + Swiss Re + Baloise + ELCA + Aveniq + Mimacom + Unit8 Switzerland + Axpo Switzerland + Ringier + MSD + SRG SSR + IBM + Google + Bühler Schweiz + Oracle Switzerland + Adnovum + EY Switzerland + ETH Zürich + Siemens Schweiz + KPMG Switzerland + Swissgrid + Suva + AO Foundation + Skyguide + Roche Switzerland + Logitech Switzerland + Swatch Group + Amazon Switzerland + Cognizant Technology Solutions AG + FISBA + GRITEC + Helbling + Maerki Baumann + Electrosuisse + Detecon Switzerland + Lufthansa Group Switzerland + Adesso Switzerland + Cudos + Eraneos Switzerland + ERNI Switzerland + Bachem + Georg Fischer Switzerland + ALSO + Bedag + Nexplore + NTT Global Data Centers + Teradata Switzerland + Swiss Life Switzerland + Sika Switzerland + Centris + Edorex + Dätwyler IT Infra + InfoGuard + SIX + Comerge + Abraxas Informatik AG + AKROS AG + amétiq ag + BSI Software + CM Informatik AG + EGELI Informatik AG + emineo AG + Hostpoint AG + Hürlimann Informatik AG + Infosoft Systems AG + isolutions AG + IWF AG + Löwenfels Partner AG + M&S Software Engineering AG + Opacc Software AG + Panter AG + Digital Architects Zurich GmbH + UMB AG + Webtouch GmbH + Manor AG + Salt Mobile SA + V-ZUG AG + Lindt & Sprüngli (Schweiz) AG",
    ),
  ).toBeInTheDocument();
  expect(runRequests).toHaveLength(1);
  expect(runRequests[0]).toMatchObject({
    sources: [
      "migros_bank",
      "die_post",
      "raiffeisen",
      "bundesverwaltung",
      "axa_schweiz",
      "sunrise",
      "iss",
      "accenture",
      "csem",
      "deloitte",
      "zuercher_kantonalbank",
      "flughafen_zuerich",
      "ubs_students_graduates",
      "abb_switzerland",
      "huawei_switzerland",
      "bdo_switzerland",
      "endress_hauser_switzerland",
      "microsoft_switzerland",
      "sap_switzerland",
      "s_peers",
      "mobiliar",
      "emmi",
      "sulzer_switzerland",
      "siegfried",
      "switch",
      "huber_suhner_switzerland",
      "stadler_it_switzerland",
      "ebp_switzerland",
      "ruag_switzerland",
      "cyberlink",
      "ergon",
      "logobject",
      "ti8m_switzerland",
      "novartis_switzerland",
      "pictet_switzerland",
      "swiss_re",
      "baloise",
      "elca",
      "aveniq",
      "mimacom",
      "unit8_switzerland",
      "axpo_switzerland",
      "ringier",
      "msd",
      "srg_ssr",
      "ibm",
      "google",
      "buhler_switzerland",
      "oracle_switzerland",
      "adnovum",
      "ey_switzerland",
      "eth_zurich",
      "siemens_switzerland",
      "kpmg_switzerland",
      "swissgrid",
      "suva",
      "ao_foundation",
      "skyguide",
      "roche_switzerland",
      "logitech_switzerland",
      "swatch_group",
      "amazon_switzerland",
      "cognizant_switzerland",
      "fisba",
      "gritec",
      "helbling",
      "maerki_baumann",
      "electrosuisse",
      "detecon_switzerland",
      "lufthansa_group_switzerland",
      "adesso_switzerland",
      "cudos",
      "eraneos_switzerland",
      "erni_switzerland",
      "bachem",
      "georg_fischer_switzerland",
      "also",
      "bedag",
      "nexplore",
      "ntt_global_data_centers_switzerland",
      "teradata_switzerland",
      "swiss_life_switzerland",
      "sika_switzerland",
      "centris",
      "edorex",
      "datwyler_it_infra",
      "infoguard",
      "six_group",
      "comerge",
      "abraxas",
      "akros",
      "ametiq",
      "bsi_software",
      "cmi",
      "egeli_informatik",
      "emineo",
      "hostpoint",
      "huerlimann_informatik",
      "infosoft",
      "isolutions",
      "iwf",
      "loewenfels",
      "m_s_software_engineering",
      "opacc",
      "panter",
      "digital_architects_zurich",
      "umb",
      "webtouch",
      "manor",
      "salt_mobile",
      "vzug",
      "lindt_spruengli_switzerland",
    ],
    aiAnalysisEnabled: true,
  });
  expect(
    screen.getAllByRole("img", { name: "Die Post logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Migros Bank logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Raiffeisen logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Bundesverwaltung logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "AXA Schweiz logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Sunrise logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "ISS Schweiz logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Accenture logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "CSEM logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Deloitte logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Zürcher Kantonalbank logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Flughafen Zürich logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "UBS logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "ABB Schweiz logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Huawei Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "BDO Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Endress+Hauser Switzerland logo" })
      .length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Microsoft Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "SAP Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "s-peers logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Mobiliar logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Emmi logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Sulzer Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Siegfried logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Switch logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Huber+Suhner Switzerland logo" })
      .length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Stadler IT Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "EBP Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "RUAG Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Cyberlink logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Ergon logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "LogObject logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "ti&m Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Novartis Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Pictet Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Swiss Re logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Baloise logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "ELCA logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Aveniq logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Mimacom logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Unit8 Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Axpo Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Ringier logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "MSD logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "SRG SSR logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "IBM logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Google logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Bühler Schweiz logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Oracle Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Adnovum logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "EY Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "ETH Zürich logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Siemens Schweiz logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "KPMG Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Swissgrid logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Suva logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "AO Foundation logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Skyguide logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Roche Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Logitech Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Swatch Group logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Amazon Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", {
      name: "Cognizant Technology Solutions AG logo",
    }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "FISBA logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "GRITEC logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Helbling logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Maerki Baumann logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Electrosuisse logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Detecon Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", {
      name: "Lufthansa Group Switzerland logo",
    }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Adesso Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Cudos logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Eraneos Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "ERNI Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Bachem logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Georg Fischer Switzerland logo" })
      .length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "ALSO logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Bedag logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Nexplore logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "NTT Global Data Centers logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Teradata Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Swiss Life Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Sika Switzerland logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Centris logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Edorex logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Dätwyler IT Infra logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "InfoGuard logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "SIX logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Comerge logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Abraxas Informatik AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "AKROS AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "amétiq ag logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "BSI Software logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "CM Informatik AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "EGELI Informatik AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "emineo AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Hostpoint AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Hürlimann Informatik AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Infosoft Systems AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "isolutions AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "IWF AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Löwenfels Partner AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", {
      name: "M&S Software Engineering AG logo",
    }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Opacc Software AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Panter AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", {
      name: "Digital Architects Zurich GmbH logo",
    }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "UMB AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Webtouch GmbH logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Manor AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "Salt Mobile SA logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", { name: "V-ZUG AG logo" }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole("img", {
      name: "Lindt & Sprüngli (Schweiz) AG logo",
    }).length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Die Post").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Migros Bank").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Raiffeisen").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Bundesverwaltung").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: AXA Schweiz").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Sunrise").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: ISS Schweiz").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Accenture").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: CSEM").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Deloitte").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Zürcher Kantonalbank").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Flughafen Zürich").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: UBS Students & Graduates").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: ABB Schweiz").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Huawei Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: BDO Switzerland").length).toBeGreaterThan(
    0,
  );
  expect(
    screen.getAllByText("Source: Endress+Hauser Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Microsoft Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: SAP Switzerland").length).toBeGreaterThan(
    0,
  );
  expect(screen.getAllByText("Source: s-peers").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Mobiliar").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Emmi").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Sulzer Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Siegfried").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Switch").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Huber+Suhner Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Stadler IT Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: EBP Switzerland").length).toBeGreaterThan(
    0,
  );
  expect(
    screen.getAllByText("Source: RUAG Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Cyberlink").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Ergon").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: LogObject").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: ti&m Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Novartis Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Pictet Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Swiss Re").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Baloise").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: ELCA").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Aveniq").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Mimacom").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Unit8 Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Axpo Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Ringier").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: MSD").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: SRG SSR").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: IBM").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Google").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Bühler Schweiz").length).toBeGreaterThan(
    0,
  );
  expect(
    screen.getAllByText("Source: Oracle Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Adnovum").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: EY Switzerland").length).toBeGreaterThan(
    0,
  );
  expect(screen.getAllByText("Source: ETH Zürich").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Siemens Schweiz").length).toBeGreaterThan(
    0,
  );
  expect(
    screen.getAllByText("Source: KPMG Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Swissgrid").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Suva").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: AO Foundation").length).toBeGreaterThan(
    0,
  );
  expect(screen.getAllByText("Source: Skyguide").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Roche Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Logitech Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Swatch Group").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Amazon Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Cognizant Technology Solutions AG").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: FISBA").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: GRITEC").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Helbling").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Maerki Baumann").length).toBeGreaterThan(
    0,
  );
  expect(screen.getAllByText("Source: Electrosuisse").length).toBeGreaterThan(
    0,
  );
  expect(
    screen.getAllByText("Source: Detecon Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Lufthansa Group Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Adesso Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Cudos").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Eraneos Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: ERNI Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Bachem").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Georg Fischer Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: ALSO").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Bedag").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Nexplore").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: NTT Global Data Centers").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Teradata Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Swiss Life Switzerland").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Sika Switzerland").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Centris").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Edorex").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Dätwyler IT Infra").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: InfoGuard").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: SIX").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Comerge").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Abraxas Informatik AG").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: AKROS AG").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: amétiq ag").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: BSI Software").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: CM Informatik AG").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: EGELI Informatik AG").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: emineo AG").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Hostpoint AG").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Hürlimann Informatik AG").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Infosoft Systems AG").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: isolutions AG").length).toBeGreaterThan(
    0,
  );
  expect(screen.getAllByText("Source: IWF AG").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Löwenfels Partner AG").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: M&S Software Engineering AG").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Opacc Software AG").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Panter AG").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Digital Architects Zurich GmbH").length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: UMB AG").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Webtouch GmbH").length).toBeGreaterThan(
    0,
  );
  expect(screen.getAllByText("Source: Manor AG").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Source: Salt Mobile SA").length).toBeGreaterThan(
    0,
  );
  expect(screen.getAllByText("Source: V-ZUG AG").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("Source: Lindt & Sprüngli (Schweiz) AG").length,
  ).toBeGreaterThan(0);
}, 30_000);

it("shows seeded vacancies and calendar events only in demo mode", async () => {
  window.history.replaceState(null, "", "#jobs");
  installApplicationWorkspaceApiMock({
    requestHandler: async (url, method) => {
      if (url.pathname === "/job-search/configs" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/jobs" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/jobs/dismissed-ids" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/applications" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/applications/events" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/profile" && method === "GET")
        return Response.json({});
      if (url.pathname === "/settings" && method === "GET")
        return Response.json(configuredAppSettings);
      if (
        (url.pathname === "/applications" ||
          url.pathname === "/applications/events") &&
        method === "PUT"
      ) {
        return Response.json([]);
      }
      return undefined;
    },
  });

  vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "0");
  const regularMode = render(<HomePage />);

  expect(await screen.findByText("0 jobs found")).toBeInTheDocument();
  expect(screen.queryByText("Stripe")).not.toBeInTheDocument();
  expect(screen.queryByText("Figma")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("link", { name: "Calendar" }));
  expect(
    await screen.findByRole("heading", { name: "Calendar" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("Technical Assessment")).not.toBeInTheDocument();
  expect(screen.queryByText("Future Wealth Group")).not.toBeInTheDocument();

  regularMode.unmount();
  window.history.replaceState(null, "", "#jobs");
  vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "1");
  render(<HomePage />);

  expect(await screen.findByText("2 jobs found")).toBeInTheDocument();
  expect(screen.getAllByText("Stripe").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Figma").length).toBeGreaterThan(0);

  fireEvent.click(screen.getByRole("link", { name: "Calendar" }));
  expect(
    await screen.findByRole("heading", { name: "Calendar" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText("Technical Assessment").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Future Wealth Group").length).toBeGreaterThan(0);
});

it("keeps preparation drafts out of Applications until they are marked as applied", async () => {
  window.history.replaceState(null, "", "#jobs");
  vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "1");
  const savedApplicationStatuses: string[] = [];

  installApplicationWorkspaceApiMock({
    requestHandler: async (url, method, init) => {
      if (url.pathname === "/job-search/configs" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/jobs" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/applications" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/applications/events" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/profile" && method === "GET")
        return Response.json({});
      if (url.pathname === "/settings" && method === "GET") {
        return Response.json({
          has_brightdata_api_key: false,
          brightdata_api_key_preview: "",
        });
      }
      if (url.pathname === "/applications" && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as {
          applications: Array<{ data: { status: string } }>;
        };
        savedApplicationStatuses.push(
          ...payload.applications.map((application) => application.data.status),
        );
        return Response.json(payload.applications);
      }
      if (url.pathname === "/applications/events" && method === "PUT")
        return Response.json([]);
      return undefined;
    },
  });

  render(<HomePage />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Prepare application" }),
  );
  expect(await screen.findByText("Application prep")).toBeInTheDocument();
  expect(
    await screen.findByRole("button", { name: "Jobs" }),
  ).toBeInTheDocument();
  await waitFor(() => expect(savedApplicationStatuses).toContain("draft"));

  fireEvent.click(screen.getByRole("button", { name: "Jobs" }));
  fireEvent.click(screen.getByRole("link", { name: "Applications" }));
  expect(await screen.findByText("No applications yet")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("link", { name: "Jobs" }));
  const continuePreparation = await screen.findByRole("button", {
    name: "Continue preparation",
  });
  fireEvent.click(continuePreparation);
  fireEvent.click(
    await screen.findByRole("button", { name: "Mark as applied" }),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Applications" }));

  expect(await screen.findByText("Applications (1)")).toBeInTheDocument();
  await waitFor(() => expect(savedApplicationStatuses).toContain("applied"));
});

it("offers decision-focused assistant questions on the Jobs page", async () => {
  window.history.replaceState(null, "", "#jobs");
  vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "1");
  const assistantRequests: Array<Record<string, unknown>> = [];
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
  installApplicationWorkspaceApiMock({
    aiPrivacySettings: {
      consentVersion: "2026-07-18.v2",
      consentBackend: "openclaw_codex",
      hasCurrentConsent: true,
    },
    requestHandler: async (url, method, init) => {
      if (url.pathname === "/job-search/configs" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/jobs" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/applications" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/applications/events" && method === "GET")
        return Response.json([]);
      if (url.pathname === "/profile" && method === "GET")
        return Response.json({});
      if (url.pathname === "/assistant/conversations" && method === "GET") {
        return Response.json([]);
      }
      if (url.pathname === "/assistant/chat/stream" && method === "POST") {
        assistantRequests.push(
          JSON.parse(String(init?.body)) as Record<string, unknown>,
        );
        return new Response(
          [
            "event: connected\ndata: {}",
            'event: delta\ndata: {"text":"Why 92% explanation","offset":19}',
            'event: done\ndata: {"metadata":{"backend":"openclaw_codex"}}',
            "",
          ].join("\n\n"),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      }
      if (url.pathname === "/settings" && method === "GET") {
        return Response.json({
          has_brightdata_api_key: false,
          brightdata_api_key_preview: "",
        });
      }
      return undefined;
    },
  });

  render(<HomePage />);

  expect(
    await screen.findByRole("button", { name: "Why 92%?" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "What to know before applying" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Analyze" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Write cover letter" }),
  ).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Why 92%?" }));
  expect(await screen.findByText("Why 92% explanation")).toBeInTheDocument();
  expect(assistantRequests).toHaveLength(1);
  expect(assistantRequests[0]).toMatchObject({
    contextKind: "job",
    contextId: "stripe-senior-product-designer",
    job: {
      id: "stripe-senior-product-designer",
      title: "Senior Product Designer",
      match: 92,
      requirements: [
        "5+ years of product design experience",
        "Strong portfolio demonstrating design thinking",
        "Experience with design systems",
        "Excellent communication skills",
      ],
    },
  });
  expect(String(assistantRequests[0].message)).toContain("Why 92%?");
  expect(String(assistantRequests[0].message)).toContain(
    "How to improve the match",
  );
});
