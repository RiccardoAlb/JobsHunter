"""Vocabolario delle competenze e riconoscimento nel testo (CV e annunci). Tutto in locale, nessuna rete.

Il vocabolario e' il dizionario `VOCAB`: categoria -> {nome mostrato: [alias]}. Per aggiungere una competenza basta una riga;
in piu' si possono mettere le proprie in `skills_extra.json` nella cartella dati:

    {"Terraform": ["terraform", "iac"], "Mia competenza": {"cat": "cloud", "aliases": ["mia comp"]}}

Il riconoscimento lavora su parole intere (mai dentro un'altra parola: "soc" non e' in "social"), senza maiuscole e senza accenti,
con singolari/plurali e le desinenze italiane piu' comuni (-a/-e/-i/-o). Prefissi speciali negli alias:

    "!IDS"  la sigla vale solo se e' scritta in MAIUSCOLO ("ids" minuscolo e' un'altra cosa)
    "?C"    parola ambigua (C, R, Go): conta solo se e' scritta esattamente cosi' E vicino ci sono altri linguaggi o parole come
            "linguaggio"/"programming" (stesso criterio prudente di `scoring._has`: meglio non vederla che inventarla)
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from functools import lru_cache

VOCAB_VERSION = 3

GENERIC_CATS = {"soft", "generali", "lingue"}  # pesano meno nel confronto: quasi tutti gli annunci le nominano

CAT_LABELS = {
    "cyber": "Cybersecurity", "sistemi": "Sistemi e IT", "rete": "Reti", "cloud": "Cloud e DevOps", "sviluppo": "Sviluppo",
    "dati": "Dati", "sanita": "Sanita'", "ufficio": "Ufficio e amministrazione", "vendite": "Vendite e clienti",
    "logistica": "Logistica e produzione", "generali": "Strumenti generali", "soft": "Competenze trasversali", "lingue": "Lingue",
}

VOCAB: dict[str, dict[str, list[str]]] = {
    "cyber": {
        "Alert Triage": ["alert triage", "triage degli alert", "triage degli allarmi", "triage di alert"],
        "SIEM": ["siem", "security information and event management"],
        "Splunk": ["splunk"], "Wazuh": ["wazuh"], "QRadar": ["qradar"], "Elastic": ["!ELK", "elk stack", "elasticsearch", "elastic stack", "opensearch"],
        "Microsoft Sentinel": ["sentinel", "microsoft sentinel", "azure sentinel"], "Graylog": ["graylog"],
        "EDR": ["edr", "xdr", "mdr", "endpoint detection", "endpoint detection and response"],
        "CrowdStrike": ["crowdstrike"], "SentinelOne": ["sentinelone", "sentinel one"], "Microsoft Defender": ["microsoft defender", "defender for endpoint", "windows defender"],
        "SOC": ["!SOC", "!SOC 2", "security operations center", "security operation center", "security operations"],
        "SOAR": ["soar"], "Incident Response": ["incident response", "risposta agli incidenti", "gestione degli incidenti", "gestione incidenti", "dfir"],
        "Threat Hunting": ["threat hunting", "caccia alle minacce"], "Threat Intelligence": ["threat intelligence", "cti"],
        "Digital Forensics": ["digital forensics", "computer forensics", "forensics", "analisi forense", "informatica forense"],
        "Malware Analysis": ["malware analysis", "analisi malware", "analisi dei malware", "reverse engineering"],
        "Penetration Testing": ["pentest", "pentesting", "penetration test", "penetration testing", "pen test", "vapt", "ethical hacking", "ethical hacker"],
        "Vulnerability Assessment": ["vulnerability assessment", "vulnerability management", "gestione delle vulnerabilita", "analisi delle vulnerabilita", "vulnerability scanning"],
        "Red Team": ["red team", "red teaming"], "Blue Team": ["blue team"], "Purple Team": ["purple team"],
        "Nmap": ["nmap"], "Metasploit": ["metasploit"], "Burp Suite": ["burp", "burp suite"], "Nessus": ["nessus", "openvas", "qualys", "tenable"],
        "Wireshark": ["wireshark", "tshark"], "Kali Linux": ["kali", "kali linux"], "Hydra": ["hydra"], "John the Ripper": ["john the ripper", "hashcat"],
        "OWASP": ["owasp", "owasp top 10", "owasp top ten"], "SQL Injection": ["sql injection", "sqli"], "XSS": ["!XSS", "cross site scripting"],
        "Web Security": ["web application security", "sicurezza delle applicazioni web", "appsec", "application security", "dast", "sast"],
        "MITRE ATT&CK": ["mitre", "mitre att ck", "att ck", "attck"], "Cyber Kill Chain": ["kill chain"],
        "IDS/IPS": ["!IDS", "!IPS", "ids ips", "intrusion detection", "intrusion prevention", "snort", "suricata", "zeek"],
        "Firewall": ["firewall", "fortigate", "palo alto", "pfsense", "check point", "next generation firewall", "ngfw", "opnsense"],
        "WAF": ["!WAF", "web application firewall"], "DLP": ["!DLP", "data loss prevention"],
        "IAM": ["!IAM", "identity and access management", "gestione delle identita", "identity management"],
        "PAM": ["!PAM", "privileged access management", "cyberark"], "MFA": ["!MFA", "multi factor authentication", "autenticazione a due fattori", "2fa"],
        "SSO": ["!SSO", "single sign on"], "Zero Trust": ["zero trust"],
        "ISO 27001": ["iso 27001", "iso27001", "iso iec 27001", "27001"], "NIS2": ["nis2", "nis 2", "direttiva nis"], "GDPR": ["gdpr", "data protection", "protezione dei dati"],
        "NIST": ["nist", "nist csf"], "Risk Assessment": ["risk assessment", "analisi del rischio", "analisi dei rischi", "risk management", "gestione del rischio"],
        "Compliance": ["compliance", "conformita normativa", "grc"], "Audit": ["audit", "auditing", "it audit", "security audit"],
        "PCI DSS": ["pci dss", "pci compliance"], "SOC 2": ["!SOC 2"], "Cybersecurity": ["cybersecurity", "cyber security", "sicurezza informatica", "information security", "infosec", "sicurezza delle informazioni"],
        "Crittografia": ["crittografia", "cryptography", "encryption", "cifratura", "pki"],
        "VPN": ["!VPN", "vpn", "ipsec", "openvpn", "wireguard"], "Phishing": ["phishing", "anti phishing", "security awareness"],
        "CTF": ["!CTF", "capture the flag", "hack the box", "hackthebox", "tryhackme", "try hack me"],
        "OSCP": ["oscp"], "CEH": ["!CEH", "certified ethical hacker"], "CISSP": ["cissp"], "CompTIA Security+": ["security+", "comptia security", "sec+"],
        "eJPT": ["ejpt"], "CISM": ["!CISM"], "CISA": ["!CISA"], "Security Hardening": ["hardening", "system hardening", "cis benchmark"],
        "Sysmon": ["sysmon"], "YARA": ["yara"], "Sigma": ["sigma rules", "regole sigma"], "Network Security": ["network security", "sicurezza di rete", "sicurezza delle reti"],
        "Cloud Security": ["cloud security", "sicurezza cloud", "casb", "cspm"], "DevSecOps": ["devsecops"],
        "Mobile Security": ["mobile security", "mdm"], "OT/ICS Security": ["ics security", "scada", "ot security"],
        "Log Analysis": ["log analysis", "analisi dei log", "analisi log", "log management", "gestione dei log"],
        "Active Directory Security": ["bloodhound", "kerberoasting", "mimikatz"],
    },
    "sistemi": {
        "Linux": ["linux", "gnu linux", "unix", "ubuntu", "debian", "centos", "red hat", "rhel", "rocky linux", "almalinux", "suse"],
        "Windows Server": ["windows server", "win server", "windows server 2019", "windows server 2022", "windows server 2016"],
        "Windows": ["windows", "windows 10", "windows 11", "microsoft windows"], "macOS": ["macos", "mac os", "os x"],
        "Active Directory": ["active directory", "ldap", "ad ds", "azure ad", "entra id", "microsoft entra"], "Group Policy": ["group policy", "gpo", "criteri di gruppo"],
        "Microsoft 365": ["microsoft 365", "office 365", "m365", "o365", "exchange online", "sharepoint", "microsoft teams"],
        "Exchange": ["exchange server"], "Intune": ["intune", "sccm", "endpoint manager", "configuration manager"],
        "PowerShell": ["powershell", "power shell"], "Bash": ["bash", "shell scripting", "shell script", "scripting shell", "zsh"],
        "VMware": ["vmware", "vsphere", "esxi", "vcenter"], "Hyper-V": ["hyper v", "hyperv"], "Proxmox": ["proxmox"],
        "Virtualizzazione": ["virtualizzazione", "virtualization", "virtual machine", "macchine virtuali", "virtualbox", "kvm", "qemu"],
        "Backup": ["backup", "disaster recovery", "veeam", "business continuity", "backup and recovery", "ripristino"],
        "Help Desk": ["help desk", "helpdesk", "service desk", "servicedesk", "assistenza tecnica", "supporto tecnico", "supporto utenti", "assistenza utenti", "technical support", "it support", "assistenza informatica", "supporto it", "second level"],
        "Ticketing": ["ticketing", "ticketing system", "jira service management", "servicenow", "zendesk", "glpi", "otrs"],
        "ITIL": ["itil", "itil v4", "gestione dei servizi it", "it service management", "itsm"],
        "Monitoraggio": ["monitoring", "monitoraggio", "zabbix", "nagios", "prometheus", "grafana", "pandora fms", "prtg", "observability"],
        "Server": ["server", "gestione server", "amministrazione server", "system administration", "amministrazione di sistema", "sysadmin", "system administrator", "amministratore di sistema", "amministratore di sistemi", "sistemista"],
        "Storage": ["storage", "!NAS", "netapp", "raid", "zfs", "ceph"], "Samba": ["samba", "smb"],
        "DNS": ["dns"], "DHCP": ["dhcp"], "Web Server": ["apache", "nginx", "iis", "web server", "tomcat", "haproxy"],
        "Mail Server": ["postfix", "dovecot", "mail server", "smtp"], "Cron": ["cron", "crontab", "systemd"],
        "SSH": ["ssh", "openssh"], "Hardware": ["hardware", "assemblaggio pc", "riparazione pc", "manutenzione hardware"],
        "Terminal Server": ["rds", "remote desktop", "terminal server", "citrix", "vdi"], "Printing": ["stampanti", "print server"],
        "Patch Management": ["patch management", "gestione delle patch", "wsus", "aggiornamenti di sicurezza"],
        "Ansible": ["ansible"], "Puppet": ["puppet", "chef infra", "chef cookbook", "saltstack"],
        "Telefonia VoIP": ["voip", "centralino", "asterisk", "3cx", "telefonia"], "SCCM": ["sccm"],
    },
    "rete": {
        "TCP/IP": ["tcp ip", "tcp/ip", "tcpip", "protocolli di rete", "modello osi", "osi", "tcp", "udp", "icmp"],
        "Networking": ["networking", "reti", "reti informatiche", "reti di computer", "lan", "wan", "network administration", "amministrazione di rete", "amministrazione di reti", "rete aziendale"],
        "Routing e Switching": ["routing", "switching", "routing and switching", "bgp", "ospf", "eigrp", "router", "vlan", "vlans"],
        "Cisco": ["cisco", "packet tracer", "ccna", "ccnp", "ccent", "cisco ios", "cisco packet tracer"], "Juniper": ["juniper", "junos"],
        "MikroTik": ["mikrotik", "routeros"], "Ubiquiti": ["ubiquiti", "unifi"], "Fortinet": ["fortinet", "fortigate", "fortianalyzer"],
        "Wi-Fi": ["wi fi", "wifi", "wlan", "wireless", "802 11"], "Load Balancing": ["load balancer", "load balancing", "bilanciamento del carico"],
        "NAT": ["!NAT", "port forwarding"], "SD-WAN": ["sd wan", "sdwan"], "Proxy": ["proxy", "squid", "reverse proxy"],
        "Subnetting": ["subnetting", "subnet", "vlsm", "cidr", "indirizzamento ip"], "Cablaggio": ["cablaggio", "cablaggio strutturato", "fibra ottica", "cavi di rete"],
        "Telecomunicazioni": ["telecomunicazioni", "telecom", "5g", "lte", "radiofrequenza"], "Mininet": ["mininet", "sdn", "openflow"],
        "Packet Analysis": ["packet analysis", "analisi del traffico", "analisi dei pacchetti", "tcpdump", "pcap"],
    },
    "cloud": {
        "AWS": ["aws", "amazon web services", "ec2", "s3", "lambda", "cloudformation"], "Azure": ["azure", "microsoft azure"],
        "Google Cloud": ["gcp", "google cloud", "google cloud platform", "bigquery"], "Cloud": ["cloud", "cloud computing", "cloud native", "iaas", "paas", "saas"],
        "Docker": ["docker", "container", "containers", "containerizzazione", "dockerfile", "docker compose"],
        "Kubernetes": ["kubernetes", "k8s", "openshift", "helm", "k3s"], "Terraform": ["terraform", "iac", "infrastructure as code", "opentofu"],
        "CI/CD": ["ci cd", "ci/cd", "cicd", "continuous integration", "continuous delivery", "continuous deployment", "jenkins", "gitlab ci", "github actions", "azure devops", "circleci", "argo cd", "argocd"],
        "DevOps": ["devops", "sre", "site reliability", "site reliability engineering"], "Git": ["git", "github", "gitlab", "bitbucket", "version control", "controllo di versione"],
        "Serverless": ["serverless", "azure functions", "cloud functions"], "Microservizi": ["microservizi", "microservices", "microservice", "architettura a microservizi"],
        "Linux Containers": ["lxc", "podman"], "OpenStack": ["openstack"], "Vagrant": ["vagrant"], "Cloudflare": ["cloudflare"],
    },
    "sviluppo": {
        "Python": ["python", "python3", "python 3", "django", "flask", "fastapi", "pandas", "numpy"],
        "JavaScript": ["javascript", "js", "ecmascript", "es6", "nodejs", "node js", "jquery"], "TypeScript": ["typescript"],
        "Java": ["java", "java ee", "jakarta ee", "jvm", "spring boot", "spring framework", "spring mvc", "hibernate"], "Kotlin": ["kotlin"],
        "C#": ["csharp", "c sharp", "asp net", "dotnet", "net core", "net framework", ".net"], "C++": ["cplusplus", "c plus plus", "cpp"],
        "C": ["?C", "c language", "linguaggio c", "ansi c", "embedded c"], "Go": ["golang", "?Go"], "Rust": ["rust"], "PHP": ["php", "laravel", "symfony", "wordpress", "drupal"],
        "Ruby": ["ruby", "ruby on rails"], "Perl": ["perl"], "Swift": ["=Swift", "swiftui", "ios development", "sviluppo ios"], "Dart/Flutter": ["flutter", "dart"],
        "Scala": ["?Scala"], "Assembly": ["assembly", "assembler", "asm", "x86 assembly", "arm assembly", "risc v"], "Lua": ["lua"],
        "HTML": ["html", "html5"], "CSS": ["css", "css3", "sass", "scss", "tailwind", "bootstrap"], "React": ["react", "reactjs", "react js", "react native", "redux", "next js", "nextjs"],
        "Angular": ["angular", "angularjs"], "Vue": ["vue", "vuejs", "vue js", "nuxt"], "Frontend": ["frontend", "front end", "sviluppo frontend", "front end development", "sviluppatore frontend"],
        "Backend": ["backend", "back end", "sviluppo backend", "back end development", "sviluppatore backend"], "Full Stack": ["full stack", "fullstack", "sviluppatore full stack"],
        "REST API": ["rest api", "restful", "api rest", "api", "apis", "graphql", "web services", "soap", "openapi", "swagger", "json", "xml"],
        "Android": ["android", "android studio", "sviluppo android"], "Unity": ["=Unity", "unreal engine", "game development"],
        "Testing": ["unit test", "unit testing", "test automation", "automazione dei test", "pytest", "junit", "selenium", "cypress", "tdd", "test driven development", "qa", "quality assurance", "testing"],
        "Agile": ["agile", "scrum", "kanban", "metodologie agili", "sprint planning", "sprint review", "sprint backlog", "scrum master", "jira"], "OOP": ["oop", "object oriented", "programmazione a oggetti", "programmazione orientata agli oggetti", "design pattern", "design patterns"],
        "Algoritmi": ["algoritmi", "algorithms", "strutture dati", "data structures"], "Scripting": ["scripting", "script", "automazione", "automation", "automatizzazione"],
        "Regex": ["regex", "regular expression", "espressioni regolari"], "Embedded": ["embedded", "firmware", "microcontrollori", "microcontroller", "arduino", "raspberry pi", "stm32", "esp32", "rtos", "iot"],
        "Programmazione": ["programmazione", "programming", "sviluppo software", "software development", "software engineering", "sviluppatore", "developer", "software developer"],
        "Odoo": ["odoo"], "WordPress": ["wordpress"], "CMS": ["cms"], "Electron": ["electron", "pywebview"],
    },
    "dati": {
        "SQL": ["sql", "t sql", "tsql", "pl sql", "plsql", "query sql", "ansi sql"], "MySQL": ["mysql", "mariadb"], "PostgreSQL": ["postgresql", "postgres", "psql"],
        "SQLite": ["sqlite"], "Oracle": ["oracle", "oracle database"], "SQL Server": ["sql server", "mssql", "microsoft sql server", "ssms", "ssis"],
        "MongoDB": ["mongodb", "mongo"], "Redis": ["redis"], "NoSQL": ["nosql", "cassandra", "dynamodb", "couchdb"], "Database": ["database", "db", "basi di dati", "basi dati", "dbms", "rdbms", "dba", "database administrator", "amministratore di database"],
        "Data Analysis": ["data analysis", "analisi dei dati", "analisi dati", "data analytics", "analytics", "data analyst"], "Excel avanzato": ["excel avanzato", "tabelle pivot", "pivot", "vlookup", "cerca verticale", "macro excel", "vba"],
        "Power BI": ["power bi", "powerbi", "dax"], "Tableau": ["tableau"], "Looker": ["looker", "looker studio", "data studio", "metabase", "qlik", "qlikview", "qlik sense"],
        "Business Intelligence": ["business intelligence", "!BI", "reportistica", "reporting", "dashboard", "kpi"], "ETL": ["etl", "elt", "data pipeline", "data pipelines", "data warehouse", "dwh", "data warehousing", "data lake"],
        "Spark": ["=Spark", "pyspark", "hadoop", "databricks", "kafka", "airflow", "dbt", "snowflake"], "Machine Learning": ["machine learning", "!ML", "apprendimento automatico", "deep learning", "scikit learn", "sklearn", "tensorflow", "keras", "pytorch", "xgboost"],
        "AI": ["!AI", "artificial intelligence", "intelligenza artificiale", "llm", "llms", "generative ai", "ia generativa", "nlp", "natural language processing", "chatgpt", "prompt engineering"],
        "Statistica": ["statistica", "statistics", "statistical", "analisi statistica", "regressione", "regression", "spss", "sas programming"], "R": ["rstudio", "r studio", "tidyverse", "ggplot", "ggplot2", "?R", "r language", "linguaggio r"],
        "Jupyter": ["jupyter", "jupyter notebook", "notebook", "colab"], "Matplotlib": ["matplotlib", "seaborn", "plotly"], "Data Science": ["data science", "data scientist", "scienza dei dati"],
        "Data Engineering": ["data engineering", "data engineer", "ingegneria dei dati"], "Data Quality": ["data quality", "qualita dei dati", "data cleaning", "pulizia dei dati", "data governance", "master data"],
        "Google Analytics": ["google analytics", "ga4", "google tag manager", "gtm"], "Web Scraping": ["web scraping", "scraping", "beautifulsoup", "scrapy"], "GIS": ["!GIS", "qgis", "arcgis"],
    },
    "sanita": {
        "Assistenza infermieristica": ["assistenza infermieristica", "infermiere", "infermieristica", "nursing", "registered nurse", "infermieristico", "assistenza ai pazienti", "patient care", "cura del paziente", "assistenza al paziente"],
        "BLS/BLSD": ["bls", "blsd", "basic life support", "rianimazione cardiopolmonare", "rcp", "acls", "als", "pals"], "Somministrazione terapie": ["somministrazione terapie", "somministrazione di farmaci", "terapia farmacologica", "somministrazione della terapia", "gestione terapie", "medication administration"],
        "Prelievi": ["prelievi", "prelievo venoso", "venipuntura", "prelievi ematici", "venipunture"], "Triage": ["triage"], "Pronto Soccorso": ["pronto soccorso", "emergency room", "emergenza urgenza", "emergenza", "118", "er nurse"],
        "Terapia intensiva": ["terapia intensiva", "icu", "intensive care", "rianimazione", "utic", "cardiologia"], "Sala operatoria": ["sala operatoria", "strumentista", "operating room", "chirurgia"],
        "Cartella clinica": ["cartella clinica", "cartella infermieristica", "medical records", "documentazione sanitaria", "ehr", "cartella clinica elettronica"], "ECG": ["ecg", "elettrocardiogramma", "elettrocardiografia"],
        "Medicazioni": ["medicazioni", "medicazione", "gestione delle ferite", "wound care", "lesioni da pressione", "piaghe da decubito"], "Igiene e sterilizzazione": ["sterilizzazione", "igiene ospedaliera", "controllo delle infezioni", "infection control", "sanificazione", "disinfezione"],
        "Geriatria": ["geriatria", "anziani", "assistenza agli anziani", "=RSA", "case di riposo", "geriatrics", "assistenza domiciliare", "adi"], "Pediatria": ["pediatria", "pediatrics", "neonatologia", "ostetricia", "pediatrico"],
        "Primo soccorso": ["primo soccorso", "first aid"], "Salute mentale": ["salute mentale", "psichiatria", "mental health", "psicologia"], "Farmacologia": ["farmacologia", "pharmacology", "farmacia", "farmacista", "pharmacy"], "Fisioterapia": ["fisioterapia", "fisioterapista", "riabilitazione", "physiotherapy"],
        "OSS": ["!OSS", "operatore socio sanitario", "operatore socio assistenziale", "asa", "oss"], "Radiologia": ["radiologia", "radiology", "tac", "risonanza magnetica", "diagnostica per immagini"], "Laboratorio": ["laboratorio analisi", "tecnico di laboratorio", "laboratory", "analisi cliniche"],
        "Dialisi": ["dialisi", "dialysis", "nefrologia"], "Oncologia": ["oncologia", "oncology", "chemioterapia"], "Sicurezza sul lavoro": ["sicurezza sul lavoro", "d lgs 81", "dlgs 81", "81 08", "rspp", "hse", "ehs", "health and safety", "salute e sicurezza"],
        "Disabili": ["disabilita", "assistenza ai disabili", "educatore", "educatrice", "educatore professionale", "oss disabili"],
    },
    "ufficio": {
        "Contabilità": ["contabilita", "contabilita generale", "contabilita ordinaria", "contabilita fornitori", "contabile", "accounting", "bookkeeping", "prima nota", "bilancio", "bilanci", "financial statements", "chiusura di bilancio", "chiusure contabili"],
        "Fatturazione": ["fatturazione", "fatturazione elettronica", "fatture", "invoicing", "ciclo attivo", "ciclo passivo", "fatturazione attiva", "fatturazione passiva"], "Paghe e contributi": ["paghe", "paghe e contributi", "payroll", "cedolini", "buste paga", "elaborazione paghe"],
        "Fiscale": ["fiscalita", "adempimenti fiscali", "dichiarazione dei redditi", "iva", "dichiarazioni fiscali", "tax", "f24", "modello unico", "770"], "Controllo di gestione": ["controllo di gestione", "controlling", "budgeting", "forecasting", "financial planning", "fp a", "tesoreria"],
        "SAP": ["sap", "sap erp", "sap fico", "sap s 4hana", "sap hana", "sap mm", "sap sd", "sap b1", "s 4hana"], "ERP": ["erp", "sage x3", "gestionale", "gestionali", "teamsystem", "zucchetti", "dynamics 365", "navision", "business central", "mexal", "passepartout", "netsuite"],
        "Segreteria": ["segreteria", "segretaria", "segretario", "segreteria amministrativa", "back office", "backoffice", "reception", "receptionist", "front office", "centralinista", "office manager", "addetto alla segreteria", "addetta alla segreteria", "assistente amministrativo", "assistente amministrativa", "impiegato amministrativo", "impiegata amministrativa"],
        "Gestione documentale": ["gestione documentale", "archiviazione", "archivio", "protocollo", "data entry", "inserimento dati", "document management"], "Risorse umane": ["risorse umane", "human resources", "recruiting", "recruiter", "selezione del personale", "talent acquisition", "onboarding", "!HR", "ricerca e selezione", "formazione del personale", "gestione del personale"],
        "Appalti e gare": ["gare d appalto", "appalti", "gare", "procurement", "acquisti", "ufficio acquisti", "purchasing", "negoziazione con i fornitori", "gestione fornitori", "codice degli appalti", "mepa", "tender"], "Legale": ["ufficio legale", "consulenza legale", "assistente legale", "affari legali", "contrattualistica", "contratti commerciali", "contract management", "gestione contratti", "paralegal", "avvocato", "diritto civile", "diritto commerciale", "diritto del lavoro", "legal counsel"],
        "Project Management": ["project management", "project manager", "gestione progetti", "gestione di progetti", "pmp", "prince2", "project management institute", "gantt", "pmo", "program manager", "product owner"], "Customer Care": ["customer care", "assistenza clienti", "servizio clienti", "customer support", "customer service", "call center", "contact center", "assistenza alla clientela", "customer success"],
    },
    "vendite": {
        "Vendite": ["vendite", "vendita", "sales", "sales manager", "account manager", "venditore", "venditrice", "addetto vendite", "addetta vendite", "business developer", "business development", "commerciale", "area manager", "key account", "key account manager", "agente di commercio", "inside sales", "sdr", "bdr"],
        "CRM": ["crm", "salesforce", "hubspot", "zoho", "pipedrive", "microsoft dynamics", "gestione clienti", "customer relationship management"], "Trattativa": ["trattativa", "trattative", "negoziazione", "negotiation", "chiusura contratti", "closing", "acquisizione clienti", "lead generation", "prospecting", "cold calling", "sviluppo portafoglio clienti"],
        "Marketing": ["marketing", "digital marketing", "marketing digitale", "seo", "sem", "google ads", "adwords", "facebook ads", "meta ads", "campagne pubblicitarie", "email marketing", "marketing automation", "content marketing", "branding", "social media", "social media marketing", "social media manager", "copywriting", "copywriter", "community manager", "content creator", "growth hacking", "performance marketing"],
        "E-commerce": ["e commerce", "ecommerce", "shopify", "woocommerce", "magento", "prestashop", "amazon seller", "marketplace", "vendita online", "amazon fba"], "Retail": ["retail", "negozio", "punto vendita", "commesso", "commessa", "addetto vendita", "addetta alla vendita", "visual merchandising", "cassiere", "cassiera", "banconista", "gestione del punto vendita", "store manager", "merchandising"],
        "Ristorazione": ["ristorazione", "cameriere", "cameriera", "barista", "barman", "cuoco", "cuoca", "chef", "cucina", "pizzaiolo", "haccp", "sala bar", "banqueting", "catering", "hospitality", "hotel", "albergo", "front desk"],
        "Turismo": ["turismo", "tourism", "agenzia viaggi", "tour operator", "booking", "biglietteria", "ricettivo"], "Comunicazione": ["comunicazione aziendale", "ufficio stampa", "pubbliche relazioni", "!PR", "public relations", "giornalismo", "editoria", "redazione", "traduzione", "traduttore", "traduttrice", "interprete"],
        "Grafica": ["grafica", "graphic design", "graphic designer", "grafico", "photoshop", "illustrator", "indesign", "figma", "canva", "ui ux", "!UX", "!UI", "ux design", "ui design", "adobe creative suite", "premiere", "after effects", "video editing", "montaggio video", "fotografia", "motion graphics", "sketch", "web design"],
    },
    "logistica": {
        "Magazzino": ["magazzino", "magazziniere", "magazziniera", "gestione magazzino", "warehouse", "warehouse management", "wms", "picking", "packing", "inventario", "inventari", "stoccaggio", "movimentazione merci", "carico e scarico", "carico scarico", "addetto al magazzino", "addetta al magazzino", "logistica di magazzino", "scaffalatura"],
        "Carrello elevatore": ["carrello elevatore", "carrelli elevatori", "muletto", "mulettista", "carrellista", "patentino muletto", "patentino carrello elevatore", "transpallet", "forklift", "reach truck", "stacker", "traspallet", "carrello retrattile"],
        "Logistica": ["logistica", "logistics", "supply chain", "catena di fornitura", "spedizioni", "spedizioniere", "trasporti", "trasporto merci", "shipping", "freight forwarding", "dogana", "customs", "import export", "corriere", "autista", "last mile", "pianificazione trasporti", "trasportatore", "gestione flotta", "pianificazione trasporti"],
        "Patente": ["patente b", "patente c", "patente ce", "patente cqc", "cqc", "patente c e", "adr", "patente di guida", "patentino", "patente a", "patente d"],
        "Produzione": ["produzione", "linea di produzione", "manufacturing", "operaio", "operaio specializzato", "operatore di produzione", "addetto alla produzione", "addetta alla produzione", "assemblaggio", "montaggio", "operatore di linea", "lean", "lean manufacturing", "kaizen", "six sigma", "5s", "oee", "lavoro a turni", "ciclo continuo", "confezionamento", "imballaggio", "operatore macchine"],
        "Manutenzione": ["manutenzione", "manutentore", "manutenzione industriale", "manutenzione meccanica", "manutenzione elettrica", "manutentore elettrico", "manutentore meccanico", "maintenance", "riparazione", "troubleshooting", "diagnostica guasti", "ricerca guasti", "assistenza tecnica macchinari", "elettromeccanico", "elettricista", "idraulico", "impiantista", "termoidraulico", "frigorista", "meccanico", "tecnico manutentore", "carpentiere"],
        "PLC": ["plc", "scada", "siemens s7", "tia portal", "automazione industriale", "hmi", "azionamenti", "inverter", "robotica", "ladder", "industry 4 0", "industria 4 0", "pneumatica", "oleodinamica", "controllo numerico", "cnc", "programmazione cnc"],
        "CAD": ["cad", "autocad", "solidworks", "catia", "revit", "bim", "archicad", "sketchup", "fusion 360", "disegno tecnico", "progettazione meccanica", "disegno meccanico", "progettazione cad", "solid edge", "rhino", "3d modeling", "stampa 3d"],
        "Controllo qualita": ["controllo qualita", "quality control", "qualita", "qualita aziendale", "iso 9001", "iso 14001", "iso 45001", "ispezione", "collaudo", "quality manager", "quality assurance engineer", "sistema qualita", "certificazioni iso", "haccp", "gmp", "metrologia", "audit qualita", "non conformita"],
        "Edilizia": ["edilizia", "cantiere", "muratore", "carpenteria", "ponteggi", "capocantiere", "geometra", "direzione lavori", "computo metrico", "sicurezza cantiere", "csp", "cse", "imbianchino", "cartongessista", "piastrellista", "posatore", "gruista", "escavatorista", "operatore edile", "ristrutturazione", "ristrutturazioni", "primus", "termotecnica"],
        "Agricoltura": ["agricoltura", "agricolo", "trattore", "trattorista", "raccolta", "serre", "vivaio", "allevamento", "agronomo", "viticoltura", "vendemmia", "potatura", "giardiniere", "giardinaggio", "manutenzione del verde", "operaio agricolo", "operaio agricolo generico", "agroalimentare"],
        "Pulizie": ["pulizie", "addetto alle pulizie", "addetta alle pulizie", "pulizia", "sanificazione ambienti", "operatore ecologico", "facility", "facility management", "portierato", "custode", "vigilanza", "guardia giurata", "addetto alla sicurezza", "steward", "sorveglianza", "security guard", "antincendio", "addetto antincendio"],
    },
    "generali": {
        "Excel": ["excel", "microsoft excel", "fogli di calcolo", "spreadsheet", "google sheets", "fogli google"], "Word": ["=Word", "microsoft word", "elaborazione testi"], "PowerPoint": ["powerpoint", "microsoft powerpoint", "presentazioni", "keynote", "google slides"],
        "Pacchetto Office": ["pacchetto office", "microsoft office", "ms office", "suite office", "libreoffice", "openoffice", "google workspace", "g suite", "gsuite", "outlook", "strumenti informatici", "strumenti office", "uso del computer"],
        "Notion": ["=Notion", "trello", "asana", "monday com", "confluence", "=Slack", "obsidian", "airtable", "clickup"], "Documentazione": ["documentazione", "documentazione tecnica", "technical writing", "redazione di documenti", "reportistica tecnica", "redazione report", "stesura di report", "writeup", "write up"],
        "Patente B": ["patente b", "patente di guida", "automunito", "automunita", "munito di patente", "auto propria", "disponibilita a spostamenti"], "Sicurezza": ["sicurezza sul posto di lavoro"], "Formazione": ["trainer", "formatore", "docente", "insegnante", "teaching", "tutor", "tutoraggio", "docenza", "lezioni private", "didattica", "maestra", "maestro", "educatrice", "insegnamento", "ripetizioni", "e learning"],
        "Ricerca": ["ricerca scientifica", "ricercatore", "laboratorio", "r d", "ricerca e sviluppo", "sperimentazione", "analisi di laboratorio"],
    },
    "soft": {
        "Lavoro di squadra": ["lavoro di squadra", "lavoro in team", "lavorare in team", "teamwork", "team work", "spirito di squadra", "collaborazione", "collaboration", "lavoro in gruppo", "capacita di lavorare in team", "team player", "affiatamento"],
        "Problem solving": ["problem solving", "risoluzione dei problemi", "risoluzione di problemi", "problem solver", "capacita di risolvere problemi", "pensiero critico", "critical thinking", "analytical skills", "capacita analitiche", "pensiero analitico", "orientamento al risultato", "orientamento ai risultati"],
        "Comunicazione efficace": ["comunicazione efficace", "capacita comunicative", "buone capacita comunicative", "communication skills", "ottime doti comunicative", "doti comunicative", "capacita relazionali", "doti relazionali", "ascolto attivo", "public speaking"],
        "Autonomia": ["autonomia", "autonomo", "autonoma", "autonomous", "self motivated", "proattivita", "proattivo", "proattiva", "proactive", "iniziativa", "spirito di iniziativa", "autonomia operativa", "capacita di lavorare in autonomia", "intraprendenza"],
        "Gestione del tempo": ["gestione del tempo", "time management", "organizzazione", "capacita organizzative", "organizational skills", "precisione", "puntualita", "affidabilita", "gestione delle priorita", "gestione dello stress", "multitasking", "resistenza allo stress", "flessibilita", "flexibility", "attenzione ai dettagli", "attention to detail", "accuratezza", "meticolosita"],
        "Leadership": ["leadership", "gestione del team", "team leading", "coordinamento di team", "team management", "gestione di gruppi", "people management", "responsabile di team", "capo squadra", "caposquadra", "team leader"],
        "Apprendimento": ["capacita di apprendimento", "voglia di imparare", "fast learner", "learning agility", "predisposizione all apprendimento", "volonta di apprendere"],
    },
    "lingue": {
        "Inglese": ["inglese", "english", "lingua inglese", "ottimo inglese", "buon inglese", "buona conoscenza dell inglese", "toefl", "ielts", "cambridge"],
        "Tedesco": ["tedesco", "german", "lingua tedesca", "deutsch"], "Francese": ["francese", "french", "lingua francese", "francais"],
        "Spagnolo": ["spagnolo", "spanish", "lingua spagnola", "espanol", "castigliano"], "Portoghese": ["portoghese", "portuguese"], "Russo": ["russo", "russian"],
        "Cinese": ["cinese", "chinese", "mandarino", "mandarin"], "Arabo": ["arabo", "arabic"], "Giapponese": ["giapponese", "japanese"], "Olandese": ["olandese", "dutch"], "Polacco": ["polacco", "polish"], "Rumeno": ["rumeno", "romanian"],
        "Italiano": ["italiano", "italian", "lingua italiana", "madrelingua italiana"],
    },
}

# la lingua da cercare nei testi e il nome mostrato
LANG_NAMES = list(VOCAB["lingue"].keys())
# i soli alias "puliti" di una lingua (nome della lingua): servono al rilevamento del livello nel CV
LANG_WORDS = {"Inglese": ("inglese", "english"), "Tedesco": ("tedesco", "german", "deutsch"), "Francese": ("francese", "french", "francais"),
              "Spagnolo": ("spagnolo", "spanish", "espanol"), "Portoghese": ("portoghese", "portuguese"), "Russo": ("russo", "russian"),
              "Cinese": ("cinese", "chinese", "mandarino", "mandarin"), "Arabo": ("arabo", "arabic"), "Giapponese": ("giapponese", "japanese"),
              "Olandese": ("olandese", "dutch"), "Polacco": ("polacco", "polish"), "Rumeno": ("rumeno", "romanian"), "Italiano": ("italiano", "italian")}

# Nomi che non sono competenze ma sono soltanto parole comuni: tolti dall'elenco "da mostrare" nel CV quando compaiono da soli (troppo generici)
_AMBIGUOUS_CONTEXT = {"programming", "programmazione", "linguaggio", "language", "linguaggi", "languages", "sviluppo", "scripting", "coding", "developer",
                      "sviluppatore", "skills", "competenze", "stack", "tecnologie", "technologies", "tools", "strumenti", "conoscenze", "knowledge", "e", "and", "ed", "o", "or", "con", "with"}
# parole-linguaggio vicino alle quali una C, una R o un Go isolati vengono accettati
# contesti in cui un termine del vocabolario NON e' la competenza (parola prima/dopo): {competenza: {"prev": {...}, "next": {...}}}
BLOCK = {
    "Linux": {"prev": {"via", "viale", "piazza", "corso", "vicolo", "largo"}},
    "Word": {"next": {"of", "count", "press", "for", "by", "play"}},
    "Swift": {"prev": {"taylor"}},
    "Unity": {"next": {"of", "in"}},
    "Notion": {"next": {"of"}},
    "Notion ": {},
    "Geriatria": {"next": {"2048", "4096", "1024", "key", "encryption", "keys"}, "prev": {"cifratura", "crittografia", "chiave", "algoritmo", "algorithm"}},
    "Microsoft Sentinel": {"next": {"one"}},
    "SOC": {"next": {"coop", "cooperativa"}},
    "Fiscale": {"prev": {"partita", "p", "con"}},
    "AI": {"next": {"clienti", "cliente", "colleghi", "fini", "fine", "giorni", "sensi", "nostri", "vostri", "quali", "quanto", "tempi", "lavori", "livelli"}},
}
_LANG_TOKENS = {"python", "java", "javascript", "cplusplus", "csharp", "bash", "rust", "golang", "ruby", "perl", "php", "typescript", "kotlin", "swift",
                "sql", "assembly", "powershell", "matlab", "scala", "fsharp", "lua", "html", "css", "labview", "verilog", "vhdl", "julia", "spss"}
_CTX_WORDS = {"linguaggio", "linguaggi", "language", "languages", "programming", "programmazione", "coding", "programmare", "scripting", "sviluppo",
              "development", "developer", "sviluppatore", "software", "embedded", "librerie", "libraries", "frameworks", "framework"}

_SPECIAL = [
    (re.compile(r"c\+\+", re.I), " cplusplus "), (re.compile(r"(?<![A-Za-z0-9])c#", re.I), " csharp "), (re.compile(r"(?<![A-Za-z0-9])f#", re.I), " fsharp "),
    (re.compile(r"(?<![A-Za-z0-9])\.net\b", re.I), " dotnet "), (re.compile(r"(?<=[A-Za-z0-9])\.(?=js\b)", re.I), ""),
    (re.compile(r"(?<![A-Za-z])(?:mitre\s+)?att&ck", re.I), " att ck "), (re.compile(r"(?<=[A-Za-z])&(?=[A-Za-z])"), " "),
    (re.compile(r"(?<=[A-Za-z])\+(?=\s|$)"), "plus "),
]
_TOKEN = re.compile(r"[A-Za-z0-9À-ɏ]+")
_VOWELS = "aeio"


def fold(text: str) -> str:
    """Minuscolo e senza accenti (come scoring.fold)."""
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def tokenize(text: str) -> list[tuple[str, str]]:
    """[(parola senza accenti e minuscola, parola com'era scritta)]. C++, C#, .NET, Node.js diventano parole semplici."""
    t = text or ""
    for rx, rep in _SPECIAL:
        t = rx.sub(rep, t)
    out = []
    for m in _TOKEN.finditer(t):
        raw = m.group()
        out.append((fold(raw), raw))
    return out


def _variants(tokens: tuple[str, ...]) -> set[tuple[str, ...]]:
    """Forme ammesse di un alias: l'ultima parola anche al plurale (-s, -es) e con le desinenze italiane -a/-e/-i/-o."""
    *head, last = tokens
    forms = {last, last + "s", last + "es"}
    if len(last) >= 6 and last[-1] in _VOWELS:
        forms |= {last[:-1] + v for v in _VOWELS}
        forms |= {last[:-1] + v + "s" for v in _VOWELS}
    elif len(last) >= 5 and last[-1] == "e":
        forms.add(last[:-1] + "i")
    return {tuple(head) + (f,) for f in forms}


class Matcher:
    """Indice di tutti gli alias: ricerca in tempo lineare sul testo (decine di annunci al millisecondo)."""

    def __init__(self, vocab: dict[str, dict[str, list[str]]]):
        self.cat: dict[str, str] = {}
        self.index: dict[str, list[tuple[tuple[str, ...], str, str]]] = {}  # prima parola -> [(parole, competenza, modo)]
        self.maxlen = 1
        for cat, skills in vocab.items():
            for name, aliases in skills.items():
                self.cat.setdefault(name, cat)
                seen = set()
                for alias in aliases:
                    mode = ""
                    if alias.startswith("="):
                        mode, alias = "S", alias[1:]
                    elif alias.startswith("!"):
                        mode, alias = "U", alias[1:]
                    elif alias.startswith("?"):
                        mode, alias = "C", alias[1:]
                    toks = tuple(t for t, _ in tokenize(alias))
                    if not toks or (toks, mode) in seen:
                        continue
                    seen.add((toks, mode))
                    # i modi U e C confrontano la grafia originale: solo la forma esatta, senza plurali
                    forms = {toks} if mode else _variants(toks)
                    tag = (mode + "|" + (alias if mode in ("C", "S") else alias.upper())) if mode else ""
                    for f in forms:
                        self.maxlen = max(self.maxlen, len(f))
                        self.index.setdefault(f[0], []).append((f, name, tag))
        for lst in self.index.values():
            lst.sort(key=lambda x: -len(x[0]))

    def find(self, text: str) -> dict[str, int]:
        """{competenza: quante volte compare}."""
        toks = tokenize(text)
        words = [t for t, _ in toks]
        found: dict[str, int] = {}
        i, n = 0, len(toks)
        while i < n:
            cands = self.index.get(words[i])
            hit = None
            if cands:
                for form, name, mode in cands:
                    k = len(form)
                    if tuple(words[i:i + k]) != form:
                        continue
                    if mode and not self._mode_ok(mode, toks, i, k):
                        continue
                    if name in BLOCK and self._blocked(BLOCK[name], words, i, k):
                        continue
                    hit = (name, k)
                    break
            if hit:
                found[hit[0]] = found.get(hit[0], 0) + 1
                i += hit[1]
            else:
                i += 1
        return found

    @staticmethod
    def _blocked(rule: dict, words: list[str], i: int, k: int) -> bool:
        prev = words[i - 1] if i > 0 else ""
        nxt = words[i + k] if i + k < len(words) else ""
        return prev in rule.get("prev", ()) or nxt in rule.get("next", ())

    @staticmethod
    def _mode_ok(mode: str, toks, i: int, k: int) -> bool:
        kind, _, spelled = mode.partition("|")
        raw = " ".join(r for _, r in toks[i:i + k])
        if kind == "S":  # come e' scritta nel vocabolario (maiuscola iniziale): "Notion" si', "notion of time" no
            return raw == spelled
        if kind == "U":
            return raw.upper() == spelled and raw == raw.upper()
        # kind == "C": scritta esattamente cosi' e con un contesto di programmazione vicino
        if raw != spelled:
            return False
        near = [toks[j][0] for j in (i - 2, i - 1, i + k, i + k + 1) if 0 <= j < len(toks)]
        return any(w in _LANG_TOKENS or w in _CTX_WORDS for w in near)


# ------------------------------------------------------------------ vocabolario esteso dall'utente ----
def _extra_path():
    from . import settings

    return settings.home() / "skills_extra.json"


def load_extra() -> dict[str, dict]:
    """Competenze aggiunte dall'utente in `skills_extra.json`. Un file rotto o strano non blocca niente: si ignora."""
    p = _extra_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict] = {}
    if not isinstance(data, dict):
        return out
    if isinstance(data.get("skills"), (list, dict)) and len(data) == 1:  # forma {"skills": [{"name":..}]}
        sk = data["skills"]
        data = {s.get("name"): s for s in sk if isinstance(s, dict)} if isinstance(sk, list) else sk
    for name, spec in list(data.items())[:2000]:
        if not isinstance(name, str) or not name.strip():
            continue
        cat, aliases = "generali", []
        if isinstance(spec, list):
            aliases = spec
        elif isinstance(spec, dict):
            cat = spec.get("cat") if spec.get("cat") in CAT_LABELS else "generali"
            aliases = spec.get("aliases") or []
        aliases = [a.strip()[:60] for a in aliases if isinstance(a, str) and a.strip()][:30]
        out[name.strip()[:60]] = {"cat": cat, "aliases": aliases}
    return out


@lru_cache(maxsize=4)
def _build(extra_key: str) -> Matcher:
    vocab = {c: {k: list(v) for k, v in d.items()} for c, d in VOCAB.items()}
    for name, spec in json.loads(extra_key).items():
        vocab.setdefault(spec["cat"], {}).setdefault(name, [])
        vocab[spec["cat"]][name] = list(dict.fromkeys(vocab[spec["cat"]][name] + [name] + spec["aliases"]))
    return Matcher(vocab)


def matcher() -> Matcher:
    return _build(json.dumps(load_extra(), sort_keys=True))


def vocab_signature() -> str:
    """Impronta del vocabolario in uso (base + personale): se cambia, i confronti vanno rifatti."""
    raw = json.dumps([VOCAB_VERSION, load_extra()], sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:10]


def category_of(skill: str) -> str:
    return matcher().cat.get(skill, "generali")


def is_generic(skill: str) -> bool:
    return category_of(skill) in GENERIC_CATS


def is_language(skill: str) -> bool:
    return category_of(skill) == "lingue"


def find_skills(text: str) -> dict[str, int]:
    """Competenze riconosciute in un testo: {nome: occorrenze}."""
    return matcher().find(text or "")


def all_skill_names() -> list[str]:
    return sorted(matcher().cat)


def resolve_name(name: str) -> str | None:
    """Se `name` e' un nome o un alias del vocabolario, il nome canonico; altrimenti None."""
    found = matcher().find(name)
    if len(found) == 1:
        return next(iter(found))
    low = fold(name).strip()
    for n in matcher().cat:
        if fold(n) == low:
            return n
    return None
