#!/home/adiack/Documents/perso/auto-publi/.venv/bin/python
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime
import oci

# Force unbuffered output for real-time logging
sys.stdout.reconfigure(line_buffering=True)

config = oci.config.from_file("~/.oci/config", "DEFAULT")
compute = oci.core.ComputeClient(config)
network = oci.core.VirtualNetworkClient(config)

TENANCY_ID = config["tenancy"]
AD_NAME = "yjcm:EU-PARIS-1-AD-1"
SUBNET_ID = "ocid1.subnet.oc1.eu-paris-1.aaaaaaaaes5prxta37immjtgy7gc5uxn3mtk4xkdwx62asmsm4pvnmgiltrq"
SSH_KEY = Path("~/.ssh/id_ed25519.pub").expanduser().read_text().strip()

# Images Ubuntu 22.04 LTS certifiées OCI
IMAGE_ARM = "ocid1.image.oc1.eu-paris-1.aaaaaaaaaoauankmjf7qjdayn6sdneozdl6fn7pmuvb3n5axzoounn4wxgga" # Ubuntu aarch64
IMAGE_X86 = "ocid1.image.oc1.eu-paris-1.aaaaaaaaxu7vd76mtg4umxthiu2364d5iazhgf457h4sgzyq46dcob6o3qoa" # Ubuntu x86

# Formes Always Free testées en rotation
SHAPE_CANDIDATES = [
    {
        "name": "Ampere A1 (1 OCPU, 4 Go RAM)",
        "shape": "VM.Standard.A1.Flex",
        "image_id": IMAGE_ARM,
        "shape_config": oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=1.0, memory_in_gbs=4.0),
    },
    {
        "name": "Ampere A1 (1 OCPU, 2 Go RAM)",
        "shape": "VM.Standard.A1.Flex",
        "image_id": IMAGE_ARM,
        "shape_config": oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=1.0, memory_in_gbs=2.0),
    },
    {
        "name": "AMD Micro (1 OCPU, 1 Go RAM)",
        "shape": "VM.Standard.E2.1.Micro",
        "image_id": IMAGE_X86,
        "shape_config": None,
    },
    {
        "name": "Ampere A1 (1 OCPU, 6 Go RAM)",
        "shape": "VM.Standard.A1.Flex",
        "image_id": IMAGE_ARM,
        "shape_config": oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=1.0, memory_in_gbs=6.0),
    },
]

print("==================================================================")
print("  Surveillance et capture automatique de VPS sur Oracle Cloud")
print("  Datacenter : Paris (yjcm:EU-PARIS-1-AD-1)")
print("  Mode       : Rotation intelligente anti-429 (35s)")
print("==================================================================")

attempt = 1
candidate_idx = 0
created_instance = None

while True:
    candidate = SHAPE_CANDIDATES[candidate_idx]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] [Tentative #{attempt}] Test sur {candidate['name']}...")

    details = oci.core.models.LaunchInstanceDetails(
        compartment_id=TENANCY_ID,
        availability_domain=AD_NAME,
        shape=candidate["shape"],
        shape_config=candidate["shape_config"],
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            source_type="image",
            image_id=candidate["image_id"]
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=SUBNET_ID,
            assign_public_ip=True,
            display_name="bchef-vnic"
        ),
        display_name="bchef-vps",
        metadata={"ssh_authorized_keys": SSH_KEY}
    )

    try:
        res = compute.launch_instance(details)
        created_instance = res.data
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] >>> SUCCES MAJEUR ! INSTANCE CAPTUREE AVEC SUCCES ! <<<")
        print("  ID Instance :", created_instance.id)
        print("  Forme       :", created_instance.shape)
        break
    except oci.exceptions.ServiceError as e:
        err_msg = str(e.message).lower()
        if "out of host capacity" in err_msg:
            print(f"  -> Capacité temporairement pleine sur {candidate['name']}. Attente prochaine tentative.")
        elif e.status == 429 or "too many requests" in err_msg:
            print("  -> Rate-limit OCI (429), pause de refroidissement de 60s...")
            time.sleep(60)
        else:
            print(f"  -> Retour OCI : {e.status} {e.code} - {e.message}")

    candidate_idx = (candidate_idx + 1) % len(SHAPE_CANDIDATES)
    attempt += 1
    time.sleep(45)

# Attente que l'instance passe en statut RUNNING
print("\nAttente de passage en statut RUNNING...")
instance_id = created_instance.id
public_ip = None

for _ in range(40):
    inst = compute.get_instance(instance_id).data
    if inst.lifecycle_state == "RUNNING":
        print("L'instance est active (RUNNING) !")
        break
    time.sleep(5)

# Récupération de l'adresse IP publique
time.sleep(5)
vnics = compute.list_vnic_attachments(compartment_id=TENANCY_ID, instance_id=instance_id).data
if vnics:
    vnic_id = vnics[0].vnic_id
    vnic = network.get_vnic(vnic_id).data
    public_ip = vnic.public_ip
    print(">>> ADRESSE IP PUBLIQUE :", public_ip)

if public_ip:
    print("\nLancement immédiat du déploiement Docker sur le VPS...")
    subprocess.run(["./deploy_to_vps.sh", public_ip], check=True)
    print("\n============================================================")
    print(f"  DÉPLOIEMENT TERMINÉ ET OPÉRATIONNEL SUR http://{public_ip}:8000")
    print("============================================================")
else:
    print("Erreur : Impossible de récupérer l'adresse IP publique automatiquement.")
