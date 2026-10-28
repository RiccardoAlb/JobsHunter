import json, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import build_dedupe_cases as b
b.CASES.clear()
D, N = b.D, b.N
A, J = "adzuna", "jooble"
S = "settore"
# ---- citta' omonime o con lo stesso inizio (nodup)
for a, c in [("Santiago de Compostela","Santiago, Chile"),("Valencia, Spain","Valencia, Venezuela"),("London, UK","London, Ontario"),("Paris, France","Paris, Texas"),
             ("Portland, Oregon","Portland, Maine"),("Hamilton, New Zealand","Hamilton, Ontario"),("Perth, Australia","Perth, Scotland"),("Cordoba, Spain","Cordoba, Argentina"),
             ("Kingston, Jamaica","Kingston upon Thames"),("Richmond, Virginia","Richmond, London"),("Neustadt an der Weinstrasse","Neustadt (Holstein)"),
             ("Sankt Gallen","Sankt Augustin"),("Saint-Denis","Saint-Etienne"),("Granada, Spain","Granada, Nicaragua"),("Victoria, British Columbia","Victoria, Australia"),
             ("Newport, Wales","Newport, Rhode Island"),("Durham, UK","Durham, North Carolina"),("Springfield, Illinois","Springfield, Massachusetts"),
             ("Freiburg im Breisgau","Freiburg an der Elbe"),("Aachen","Aachen-Laurensberg")]:
    N(S,"mix","city","citta' omonime o simili",("Warehouse Supervisor","Cranfield Logistics Ltd",a,A),("Warehouse Supervisor","Cranfield Logistics Ltd",c,A))
# ---- citta' stesse (dup)
for a, c in [("Munich","Muenchen"),("Cologne","Koeln"),("Vienna","Wien"),("Prague","Praha 2"),("Geneva","Geneve"),("Zurich, Switzerland","Zuerich"),("St. Gallen","Sankt Gallen"),
             ("Freiburg im Breisgau","Freiburg"),("Valencia, Spain","Valencia"),("London, UK","London"),("Paris, France","Paris"),("Santiago de Compostela","Santiago de Compostela, Galicia"),
             ("Portland, OR","Portland, Oregon"),("Genoa","Genova"),("Naples","Napoli"),("Turin","Torino, Piemonte"),("Lisbon","Lisboa"),("Seville","Sevilla"),("Gothenburg","Goteborg"),("Antwerp","Antwerpen")]:
    D(S,"mix","city","stessa citta'",("Quality Inspector","Halvorsen Industrier AS",a,A),("Quality Inspector","Halvorsen Industrier",c,J))
# ---- forme societarie internazionali anche rare
for a, c in [("Tenaga Solutions Sdn. Bhd.","Tenaga Solutions"),("Orlando Systems Pty Ltd","Orlando Systems"),("Kovacs Trading Kft.","Kovacs Trading"),("Novak Stroje d.o.o.","Novak Stroje"),
             ("Kone Oyj","Kone"),("Equinor ASA","Equinor"),("Aurora Pte. Ltd.","Aurora"),("Sibur OOO","Sibur"),("Delhaize Le Lion BVBA","Delhaize Le Lion"),("Merck KGaA","Merck"),
             ("Femsa S.A. de C.V.","Femsa"),("Natura Cosmeticos Ltda.","Natura Cosmeticos"),("Alicorp S.A.A.","Alicorp"),("Lasse Oy Ab","Lasse"),("Voith GmbH & Co. KGaA","Voith"),
             ("Stellantis N.V.","Stellantis"),("Yildiz Holding A.S.","Yildiz Holding"),("Nordea Bank Abp","Nordea Bank"),("Tata Consultancy Services Pvt. Ltd.","Tata Consultancy Services"),
             ("Vodafone Zrt.","Vodafone")]:
    D(S,"mix","soc","forma societaria",("Maintenance Technician",a,"Brno",A),("Maintenance Technician",c,"Brno",J))
# ---- marchio contro ragione sociale / corto contro esteso
for a, c in [("Nestle","Nestle S.A."),("H&M","H&M Hennes & Mauritz AB"),("BP","BP Plc"),("3M","3M Company"),("SAP","SAP SE"),("Ryanair","Ryanair DAC"),("IBM","IBM Italia S.p.A."),
             ("Carrefour","Carrefour France SAS"),("Danone","Danone S.A."),("Michelin","Michelin Group"),("Axa","AXA France Vie"),("L'Oreal","L'Oreal Groupe")]:
    D(S,"mix","brand","marchio e ragione sociale",("Customer Advisor",a,"Lyon",A),("Customer Advisor",c,"Lyon",J))
for a, c in [("Nestle","Nestle Waters"),("Bosch","Bosch Rexroth"),("Thales","Thales Alenia Space"),("Airbus","Airbus Helicopters"),("Philips","Philips Lighting"),("Danone","Danone Nutricia"),
             ("Ford","Ford Credit"),("Honda","Honda Financial Services"),("Toyota","Toyota Material Handling"),("Shell","Shell Energy Retail")]:
    N(S,"mix","brand","unita' diverse dello stesso marchio",("Customer Advisor",a,"Lyon",A),("Customer Advisor",c,"Lyon",J))
for a, c in [("Alden Carpets","Alder Carpets"),("Brightwell Pharma","Brightwood Pharma"),("Kestrel Foods","Kestrel Fuels"),("Marlow Textiles","Marlowe Textiles Ltd")]:
    N(S,"mix","co","nomi simili",("Packer",a,"Leeds",A),("Packer",c,"Leeds",A))
# ---- refusi lunghi (dup) e corti (dup, costo accettato)
for a, c, t in [("Administrator","Adminstrator","long"),("Receptionist","Recepcionist","long"),("Electrician","Electrican","long"),("Programmer","Programer","long"),
                ("Accountant","Acountant","long"),("Technician","Tecnician","long"),("Supervisor","Supervisior","long"),("Coordinator","Cordinator","long")]:
    D(S,"en","typo","refuso lungo",(a,"Wexcombe Services Ltd","Exeter",A),(c,"Wexcombe Services","Exeter",J))
for a, c in [("Nurse","Nruse"),("Cleaner","Claener"),("Chef","Chfe"),("Cook","Cok"),("Baker","Bakre"),("Teacher","Teacehr")]:
    D(S,"en","typo","refuso corto",(a,"Wexcombe Services Ltd","Exeter",A),(c,"Wexcombe Services","Exeter",J))
# ---- mestieri che differiscono per una lettera (nodup)
for a, c in [("Baker","Banker"),("Cook","Cock"),("Sailor","Tailor"),("Dealer","Healer"),("Packer","Parker"),("Planner","Planter"),("Waiter","Writer"),("Painter","Pointer"),("Miner","Minor"),
             ("Fitter","Fitter Mate"),("Welder","Welter"),("Rider","Ryder")]:
    N(S,"en","one","una lettera cambia il mestiere",(a,"Trevelyan Group","Plymouth",A),(c,"Trevelyan Group","Plymouth",A))
# ---- abbreviazioni (dup)
for a, c in [("Asst Manager","Assistant Manager"),("Snr Engineer","Senior Engineer"),("Maintenance Tech","Maintenance Technician"),("Project Coord.","Project Coordinator"),
             ("Sales Rep","Sales Representative"),("Account Exec","Account Executive"),("Mech. Engineer","Mechanical Engineer"),("Dir. Operations","Director Operations"),
             ("Supv Warehouse","Supervisor Warehouse"),("Regional Mgr","Regional Manager"),("Sr. Accountant","Senior Accountant"),("Jr. Analyst","Junior Analyst")]:
    D(S,"en","abbr","abbreviazione",(a,"Pemberton Holdings Plc","Cardiff",A),(c,"Pemberton Holdings","Cardiff",J))
# ---- coda di rumore (dup)
for a, c in [("Nurse","Nurse - Immediate start"),("Care Assistant","Care Assistant (Remote)"),("Driver","Driver | Bristol"),("Cleaner","Cleaner: Night shift"),
             ("Electrician","Electrician - Full time - Competitive salary"),("Receptionist","Receptionist (Part time)"),("Welder","Welder - Urgent"),("Barista","Barista (Hybrid, Leeds)"),
             ("Chef","Chef - Brighton - Live in available"),("Plumber","Plumber (m/f/d) - Immediate start")]:
    D(S,"en","tail","coda di rumore",(a,"Glenhaven Care Ltd","Brighton",A),(c,"Glenhaven Care","Brighton",J))
# ---- coda che specializza (nodup)
for a, c in [("Nurse","Nurse practitioner"),("Teacher","Teacher assistant"),("Manager","Manager trainee"),("Engineer","Engineer apprentice"),("Cook","Cook helper"),
             ("Driver","Driver trainer"),("Analyst","Analyst programmer"),("Designer","Designer intern"),("Engineer - Software","Engineer - Hardware"),("Technician - Electrical","Technician - Mechanical")]:
    N(S,"en","spec","coda che specializza",(a,"Glenhaven Care Ltd","Brighton",A),(c,"Glenhaven Care","Brighton",J))
# ---- nomi composti e qualifiche tra parentesi
for a, c in [("Industriekaufmann (m/w/d)","Industriekaufmann"),("Fachinformatiker (m/w/d)","Fachinformatiker / Fachinformatikerin"),("Kfz-Mechaniker","Kfz Mechaniker"),("Lagerlogistiker","Lagerlogistiker (m/w/d)"),
             ("Mitarbeiter Kundenservice","Mitarbeiter im Kundenservice"),("Sachbearbeiter Einkauf","Sachbearbeiter (Einkauf)")]:
    D(S,"de","comp","composti e qualifiche",(a,"Brandt Werke GmbH","Kassel",A),(c,"Brandt Werke","Kassel",J))
for a, c in [("Pflegekraft Intensiv","Pflegekraft Ambulant"),("Sachbearbeiter Einkauf","Sachbearbeiter Verkauf"),("Kfz-Mechaniker","Kfz-Elektriker"),("Lagerist","Lagerleiter"),("Verkaeufer Elektro","Verkaeufer Mode")]:
    N(S,"de","comp","composti diversi",(a,"Brandt Werke GmbH","Kassel",A),(c,"Brandt Werke GmbH","Kassel",A))
# ---- livelli
for a, c in [("Junior Buyer","Senior Buyer"),("Buyer I","Buyer II"),("Chef de Partie","Sous Chef"),("Trainee Accountant","Chief Accountant"),("Level 1 Support","Level 2 Support"),("Entry Level Analyst","Lead Analyst")]:
    N(S,"en","lvl","livello",(a,"Pemberton Holdings","Cardiff",A),(c,"Pemberton Holdings","Cardiff",A))
# ---- lingue diverse (fr/es/it) dup e nodup
for a, c in [("Technicien de maintenance H/F","Technicien de maintenance"),("Responsable d'agence H/F","Responsable d'agence (F/H)"),("Gestor de cuentas","Gestor/a de cuentas"),
             ("Operaio generico","Operaio generico (M/F)"),("Addetto al banco","Addetto/a al banco"),("Educatrice","Educatore/trice")]:
    D(S,"mix","lang","genere e lingue",(a,"Duval Entreprises SAS","Lyon",A),(c,"Duval Entreprises","Lyon",J))
for a, c in [("Technicien de maintenance H/F","Technicien de laboratoire H/F"),("Responsable d'agence H/F","Responsable de magasin H/F"),("Gestor de cuentas","Gestor de compras"),
             ("Operaio generico","Operaio specializzato"),("Addetto al banco","Addetto alla cassa")]:
    N(S,"mix","lang","ruoli diversi",(a,"Duval Entreprises SAS","Lyon",A),(c,"Duval Entreprises SAS","Lyon",A))
# ---- identici facili
for t, c, l in [("Welder","Harland Yard","Belfast"),("Mechanic","Kessler Auto","Linz"),("Carer","Sunnyside Homes","Cork"),("Gardener","Greenfield Parks","Ghent"),("Painter","Bianchi Edilizia","Parma"),
                ("Cashier","Mercado Sur","Quito"),("Teacher","Hillcrest School","Hamilton, New Zealand"),("Surveyor","Dunmore Estates","Aberdeen")]:
    D(S,"mix","easy","identici",(t,c,l,A),(t,c,l,J))
# ---- tutto diverso
for a, c in [(("Welder","Harland Yard","Belfast"),("Gardener","Greenfield Parks","Belfast")),(("Mechanic","Kessler Auto","Linz"),("Cashier","Kessler Markt","Linz")),(("Carer","Sunnyside Homes","Cork"),("Surveyor","Dunmore Estates","Cork"))]:
    N(S,"mix","far","lontani",a+(A,),c+(A,))
for c in b.CASES: c["id"]="x"+c["id"][1:]
b.enrich(b.CASES)
json.dump(b.CASES, open(__import__("pathlib").Path(__file__).with_name("dedupe_blind3.json"),"w"), ensure_ascii=False, indent=1)
d=sum(c["label"]=="dup" for c in b.CASES); print(len(b.CASES), d, len(b.CASES)-d)
