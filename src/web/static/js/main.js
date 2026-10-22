function showToast(message, isError = false) {
  const toast = document.getElementById("toast-notice");
  if (!toast) return;
  toast.innerText = message;
  toast.style.display = "block";
  toast.style.borderLeftColor = isError ? "#f43f5e" : "#e35205";
  setTimeout(() => {
    toast.style.display = "none";
  }, 4000);
}

function switchTab(tabId, btn) {
  document.querySelectorAll(".tab-pane").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));

  const target = document.getElementById(tabId);
  if (target) target.classList.add("active");
  if (btn) {
    btn.classList.add("active");
    try {
      btn.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    } catch (e) {}
  }
}

async function saveProfileSettings() {
  const selectedRadio = document.querySelector('input[name="radio-profile"]:checked');
  const activeProfile = selectedRadio ? selectedRadio.value : "test";

  const testUser = document.getElementById("input-insta-test-user")?.value.trim() || "";
  const testPass = document.getElementById("input-insta-test-pass")?.value.trim() || "";
  const officialUser = document.getElementById("input-insta-official-user")?.value.trim() || "";
  const officialPass = document.getElementById("input-insta-official-pass")?.value.trim() || "";

  const formData = new FormData();
  formData.append("active_profile", activeProfile);
  if (testUser) formData.append("test_insta_user", testUser);
  if (testPass) formData.append("test_insta_pass", testPass);
  if (officialUser) formData.append("official_insta_user", officialUser);
  if (officialPass) formData.append("official_insta_pass", officialPass);

  showToast("Enregistrement du profil social...");
  try {
    const res = await fetch("/api/settings/profile", {
      method: "POST",
      body: formData,
    });
    if (res.status === 401) {
      showToast("Session expiree. Reconnexion requise...", true);
      setTimeout(() => location.href = "/login", 1200);
      return;
    }
    const data = await res.json();
    if (data.status === "success") {
      showToast(data.message || "Profil enregistre avec succes.");
      setTimeout(() => location.reload(), 1000);
    } else {
      showToast(data.detail || "Erreur lors de l'enregistrement.", true);
    }
  } catch (err) {
    showToast("Erreur de communication avec le serveur.", true);
  }
}



function copyContent(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const val = el.value || el.innerText;
  navigator.clipboard.writeText(val).then(() => {
    showToast("Texte copie dans le presse-papier.");
  }).catch(() => {
    showToast("Impossible de copier le texte.", true);
  });
}

function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.style.display = "flex";
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.style.display = "none";
    const vid = modal.querySelector("video");
    if (vid) vid.pause();
  }
}

function previewRawVideo(filename, isArchive = false) {
  const title = document.getElementById("modal-video-title");
  const player = document.getElementById("modal-video-player");
  if (title) title.innerText = (isArchive ? "Archive : " : "") + filename;
  if (player) {
    const basePath = isArchive ? "/media/processed/archive" : "/media/uploads/videos";
    player.src = `${basePath}/${filename}`;
    player.load();
    player.play();
  }
  openModal("modal-video");
}

async function archiveVideo(filename) {
  showToast(`Archivage de ${filename}...`);
  try {
    const res = await fetch(`/api/videos/archive/${encodeURIComponent(filename)}`, {
      method: "POST",
    });
    const data = await res.json();
    if (data.status === "success") {
      showToast(data.message);
      setTimeout(() => location.reload(), 800);
    } else {
      showToast(data.detail || "Erreur lors de l'archivage.", true);
    }
  } catch (err) {
    showToast("Erreur reseau.", true);
  }
}

async function restoreVideo(filename) {
  showToast(`Restauration de ${filename}...`);
  try {
    const res = await fetch(`/api/videos/restore/${encodeURIComponent(filename)}`, {
      method: "POST",
    });
    const data = await res.json();
    if (data.status === "success") {
      showToast(data.message);
      setTimeout(() => location.reload(), 800);
    } else {
      showToast(data.detail || "Erreur lors de la restauration.", true);
    }
  } catch (err) {
    showToast("Erreur reseau.", true);
  }
}

async function deleteArchivedVideo(filename) {
  if (!confirm(`Supprimer definitivement l'archive ${filename} ?`)) return;
  try {
    const res = await fetch(`/api/archive/${encodeURIComponent(filename)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (data.status === "success") {
      showToast(data.message);
      setTimeout(() => location.reload(), 800);
    } else {
      showToast(data.detail || "Erreur lors de la suppression.", true);
    }
  } catch (err) {
    showToast("Erreur reseau.", true);
  }
}

async function deleteVideo(filename) {
  if (!confirm(`Etes-vous sur de vouloir supprimer la video ${filename} ?`)) return;
  try {
    const res = await fetch(`/api/videos/${encodeURIComponent(filename)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (data.status === "success") {
      showToast(data.message);
      setTimeout(() => location.reload(), 800);
    } else {
      showToast(data.detail || "Erreur de suppression.", true);
    }
  } catch (err) {
    showToast("Erreur reseau lors de la suppression.", true);
  }
}

async function deleteStory(filename) {
  if (!confirm(`Etes-vous sur de vouloir supprimer cette image de story ?`)) return;
  try {
    const res = await fetch(`/api/stories/${encodeURIComponent(filename)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (data.status === "success") {
      showToast(data.message);
      setTimeout(() => location.reload(), 800);
    } else {
      showToast(data.detail || "Erreur de suppression.", true);
    }
  } catch (err) {
    showToast("Erreur reseau lors de la suppression.", true);
  }
}

async function handleFileUpload(inputElement, type) {
  const files = inputElement.files;
  if (!files || files.length === 0) return;

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const formData = new FormData();
    formData.append("file", file);

    showToast(`Telechargement de ${file.name}...`);

    try {
      const res = await fetch(`/api/upload/${type}`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (data.status !== "success") {
        showToast(`Erreur lors de l'upload de ${file.name}`, true);
        return;
      }
    } catch (e) {
      showToast("Erreur reseau durant le telechargement.", true);
      return;
    }
  }

  showToast("Fichiers ajoutes avec succes.");
  setTimeout(() => location.reload(), 1000);
}

// Drag and drop setup
function attachDropzone(zoneId, inputId, type) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  if (!zone || !input) return;

  ["dragenter", "dragover"].forEach(evt => {
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      zone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach(evt => {
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      zone.classList.remove("dragover");
    });
  });

  zone.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      input.files = files;
      handleFileUpload(input, type);
    }
  });
}

attachDropzone("dropzone-video-tab", "input-video-tab", "video");

async function saveHours() {
  const form = document.getElementById("form-hours");
  if (!form) return;
  const formData = new FormData(form);
  const hoursMap = {};
  formData.forEach((val, key) => {
    hoursMap[key] = val.trim();
  });

  showToast("Enregistrement des horaires...");
  try {
    const res = await fetch("/api/settings/hours", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(hoursMap),
    });
    const data = await res.json();
    if (data.status === "success") {
      showToast("Horaires mis a jour avec succes.");
      setTimeout(() => location.reload(), 1000);
    } else {
      showToast("Erreur lors de l'enregistrement.", true);
    }
  } catch (err) {
    showToast("Erreur reseau.", true);
  }
}

async function saveCredentials() {
  const geminiInput = document.getElementById("input-gemini-key");
  const instaUser = document.getElementById("input-insta-user");
  const instaPass = document.getElementById("input-insta-pass");
  const dashPass = document.getElementById("input-dash-pass");

  const formData = new FormData();
  if (geminiInput && geminiInput.value.trim()) {
    formData.append("gemini_api_key", geminiInput.value.trim());
  }
  if (instaUser) {
    formData.append("instagram_username", instaUser.value.trim());
  }
  if (instaPass && instaPass.value.trim()) {
    formData.append("instagram_password", instaPass.value.trim());
  }
  if (dashPass && dashPass.value.trim()) {
    formData.append("dashboard_password", dashPass.value.trim());
  }

  showToast("Mise a jour des identifiants...");
  try {
    const res = await fetch("/api/settings/credentials", {
      method: "POST",
      body: formData,
    });
    if (res.status === 401) {
      showToast("Session expiree. Reconnexion requise...", true);
      setTimeout(() => location.href = "/login", 1200);
      return;
    }
    const data = await res.json();
    if (data.status === "success") {
      showToast("Identifiants enregistres avec succes.");
      if (geminiInput) geminiInput.value = "";
      if (instaPass) instaPass.value = "";
      if (dashPass) dashPass.value = "";
      setTimeout(() => location.reload(), 1000);
    } else {
      showToast("Erreur lors de l'enregistrement.", true);
    }
  } catch (err) {
    showToast("Erreur de communication avec le serveur.", true);
  }

}

async function regenerateAI() {
  showToast("Analyse multimodale Gemini en cours...");
  try {
    const res = await fetch("/api/ai/regenerate", { method: "POST" });
    const data = await res.json();
    if (data.status === "success" && data.analysis) {
      const a = data.analysis;
      const hookInput = document.getElementById("hook-input");
      const descInput = document.getElementById("desc-input");
      const tagsContainer = document.getElementById("tags-container");

      if (hookInput && a.hook) hookInput.value = a.hook;
      if (descInput && a.description) descInput.value = a.description;
      if (tagsContainer && a.hashtags) {
        tagsContainer.innerHTML = a.hashtags.map(t => `<span class="tag-item">${t}</span>`).join("");
      }

      if (data.preview_video) {
        const reelPlayer = document.getElementById("reel-preview-player");
        if (reelPlayer) {
          const source = reelPlayer.querySelector("source");
          if (source) {
            source.src = `/media/processed/videos/${data.preview_video}?t=${Date.now()}`;
            reelPlayer.load();
          }
        }
      }

      showToast("Nouveaux textes generes et video pre-incrustee.");
    } else {
      showToast(data.detail || "Erreur de generation.", true);
    }
  } catch (err) {
    showToast("Erreur lors de la regeneration.", true);
  }
}

let publicationPollingInterval = null;

function updateTriggerButtons(loading, labelText = "") {
  const btnDesktop = document.getElementById("btn-trigger");
  const btnMobile = document.getElementById("btn-trigger-mobile");

  if (loading) {
    if (btnDesktop) {
      btnDesktop.disabled = true;
      btnDesktop.innerHTML = `<span>${labelText || "Traitement en cours..."}</span>`;
    }
    if (btnMobile) {
      btnMobile.disabled = true;
      btnMobile.innerHTML = `<span>${labelText || "En cours..."}</span>`;
    }
  } else {
    if (btnDesktop) {
      btnDesktop.disabled = false;
      btnDesktop.innerHTML = `<svg class="icon" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg><span>Publier maintenant</span>`;
    }
    if (btnMobile) {
      btnMobile.disabled = false;
      btnMobile.innerHTML = `<svg class="icon-sm icon" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg><span>Publier maintenant</span>`;
    }
  }
}

async function checkAndPollPublicationStatus() {
  try {
    const res = await fetch("/api/trigger/status");
    const data = await res.json();

    if (data.is_running) {
      const stepText = data.step || "Traitement en cours...";
      const pct = data.percent || 10;
      updateTriggerButtons(true, `${stepText} (${pct}%)`);
      showToast(`${pct}% : ${stepText}`);

      if (!publicationPollingInterval) {
        publicationPollingInterval = setInterval(checkAndPollPublicationStatus, 1500);
      }
    } else {
      if (publicationPollingInterval) {
        clearInterval(publicationPollingInterval);
        publicationPollingInterval = null;
      }
      if (data.status === "success") {
        updateTriggerButtons(true, "Termine (100%)");
        showToast("Publication executee avec succes.");
        setTimeout(() => location.reload(), 1500);
      } else if (data.status === "already_published") {
        updateTriggerButtons(false);
        showToast(data.step || "Publication deja effectuee aujourd'hui.", false);
        setTimeout(() => location.reload(), 1500);
      } else if (data.status === "error") {
        updateTriggerButtons(false);
        showToast(data.error || "Erreur lors de la publication.", true);
      }
    }
  } catch (err) {
    console.error("Erreur polling status :", err);
  }
}

async function triggerPublication() {
  const targetChip = document.getElementById("active-target-chip");
  const targetName = targetChip ? targetChip.innerText.trim() : "le profil actif";
  if (!confirm(`Confirmer la publication immediate sur ${targetName} ?`)) {
    return;
  }

  const hookInput = document.getElementById("hook-input");
  const descInput = document.getElementById("desc-input");
  const hookVal = hookInput ? hookInput.value.trim() : "";
  const descVal = descInput ? descInput.value.trim() : "";

  const tagElements = document.querySelectorAll("#tags-container .tag-item");
  const tags = Array.from(tagElements).map(el => el.textContent.trim()).filter(Boolean);

  updateTriggerButtons(true, "Demarrage (5%)...");
  showToast("Lancement du pipeline de publication...");

  try {
    const formData = new FormData();
    formData.append("simulation", "false");
    if (hookVal) formData.append("hook", hookVal);
    if (descVal) formData.append("description", descVal);
    if (tags.length > 0) formData.append("hashtags", JSON.stringify(tags));

    const res = await fetch("/api/trigger/publish", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();

    if (data.status === "started") {
      showToast("Publication en cours en arriere-plan...");
      if (!publicationPollingInterval) {
        publicationPollingInterval = setInterval(checkAndPollPublicationStatus, 1500);
      }
    } else if (data.status === "already_running") {
      showToast("Une publication est deja en cours.", true);
      if (!publicationPollingInterval) {
        publicationPollingInterval = setInterval(checkAndPollPublicationStatus, 1500);
      }
    } else if (data.status === "already_published") {
      showToast(data.message || "Publication deja effectuee aujourd'hui.", false);
      updateTriggerButtons(false);
    } else {
      showToast(data.message || "Erreur au lancement.", true);
      updateTriggerButtons(false);
    }
  } catch (e) {
    showToast("Erreur reseau lors du lancement.", true);
    updateTriggerButtons(false);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  fetch("/api/trigger/status")
    .then(r => r.json())
    .then(d => {
      if (d && d.is_running) {
        updateTriggerButtons(true, `${d.step || "En cours"} (${d.percent || 10}%)`);
        publicationPollingInterval = setInterval(checkAndPollPublicationStatus, 1500);
      }
    })
    .catch(() => {});

  document.querySelectorAll('input[name="radio-profile"]').forEach(radio => {
    radio.addEventListener("change", () => {
      document.querySelectorAll(".profile-option").forEach(opt => {
        opt.classList.remove("active-test", "active-official");
      });
      const parent = radio.closest(".profile-option");
      if (parent) {
        if (radio.value === "test") parent.classList.add("active-test");
        if (radio.value === "official") parent.classList.add("active-official");
      }
    });
  });
});


async function saveFrequencySettings() {
  const sel = document.getElementById("select-posts-per-day");
  if (!sel) return;
  const postsPerDay = sel.value;

  const formData = new FormData();
  formData.append("posts_per_day", postsPerDay);

  showToast("Enregistrement du rythme de publication...");
  try {
    const res = await fetch("/api/settings/frequency", {
      method: "POST",
      body: formData,
    });
    if (res.status === 401) {
      showToast("Session expiree. Reconnexion requise...", true);
      setTimeout(() => location.href = "/login", 1200);
      return;
    }
    const data = await res.json();
    if (data.status === "success") {
      showToast(data.message || "Frequence mise a jour avec succes.");
      const badge = document.getElementById("badge-posts-per-day");
      if (badge) badge.textContent = `${postsPerDay} par jour`;
      setTimeout(() => location.reload(), 1000);
    } else {
      showToast(data.detail || "Erreur lors de l'enregistrement.", true);
    }
  } catch (err) {
    showToast("Erreur reseau lors de l'enregistrement.", true);
  }
}
