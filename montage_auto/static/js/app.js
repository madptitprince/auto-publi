// BCHEF Montage Studio Front-End Logic
const API_BASE = window.__ROOT_PATH__ || (window.location.pathname.startsWith('/studio') ? '/studio' : '');
let selectedRushs = new Set();
let currentJobId = null;
let pollInterval = null;

// DOM Elements
const navItems = document.querySelectorAll('.nav-item');
const mobileNavItems = document.querySelectorAll('.mobile-nav-item');
const tabPanes = document.querySelectorAll('.tab-pane');

const btnShowLibrary = document.getElementById('btn-show-library');
const btnShowUpload = document.getElementById('btn-show-upload');
const sectionLibrary = document.getElementById('section-library');
const sectionUpload = document.getElementById('section-upload');

const rushsGrid = document.getElementById('rushs-grid');
const selectedCounter = document.getElementById('selected-counter');
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');
const btnBrowse = document.getElementById('btn-browse');
const uploadStatus = document.getElementById('upload-status');

const montageForm = document.getElementById('montage-form');
const btnSubmitMontage = document.getElementById('btn-submit-montage');

const progressCard = document.getElementById('progress-card');
const progressTitle = document.getElementById('progress-status-text');
const progressSub = document.getElementById('progress-step-text');
const progressBarFill = document.getElementById('progress-bar-fill');
const progressPct = document.getElementById('progress-pct');

const resultCard = document.getElementById('result-card');
const resultVideo = document.getElementById('result-video');
const resultHook = document.getElementById('result-hook');
const resultDesc = document.getElementById('result-desc');
const resultHashtags = document.getElementById('result-hashtags');
const resultDuration = document.getElementById('result-duration');
const btnDownloadResult = document.getElementById('btn-download-result');
const btnSendQueue = document.getElementById('btn-send-queue');

const historyContainer = document.getElementById('history-container');
const rawRushsContainer = document.getElementById('raw-rushs-container');
const historyBadge = document.getElementById('history-badge');
const rushsBadge = document.getElementById('rushs-badge');
const mobileHistoryBadge = document.getElementById('mobile-history-badge');
const mobileRushsBadge = document.getElementById('mobile-rushs-badge');
const toastEl = document.getElementById('toast');

// Initialize
function initApp() {
    initNavigation();
    initSourceSwitcher();
    initDropzone();
    initMontageForm();
    loadRushs();
    loadHistory();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}

// Tab Switcher for both desktop and mobile
function switchTab(tabId) {
    document.querySelectorAll('.nav-item, .mobile-nav-item').forEach(item => {
        if (item.dataset.tab === tabId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    tabPanes.forEach(pane => {
        if (pane.id === `tab-${tabId}`) {
            pane.classList.remove('hidden');
            pane.classList.add('active');
        } else {
            pane.classList.add('hidden');
            pane.classList.remove('active');
        }
    });

    window.scrollTo({ top: 0, behavior: 'smooth' });

    if (tabId === 'history') loadHistory();
    if (tabId === 'rushs') loadRawRushsTable();
}

// Navigation Handling
function initNavigation() {
    document.querySelectorAll('.nav-item, .mobile-nav-item').forEach(item => {
        item.addEventListener('click', () => {
            switchTab(item.dataset.tab);
        });
    });
}

// Source Switcher (Library vs Upload)
function initSourceSwitcher() {
    btnShowLibrary.addEventListener('click', () => {
        btnShowLibrary.classList.add('active');
        btnShowUpload.classList.remove('active');
        sectionLibrary.classList.remove('hidden');
        sectionUpload.classList.add('hidden');
    });

    btnShowUpload.addEventListener('click', () => {
        btnShowUpload.classList.add('active');
        btnShowLibrary.classList.remove('active');
        sectionUpload.classList.remove('hidden');
        sectionLibrary.classList.add('hidden');
    });
}

// Toast Notifications
function showToast(message, isError = false) {
    toastEl.textContent = message;
    toastEl.style.borderColor = isError ? '#ef4444' : '#10b981';
    toastEl.classList.remove('hidden');
    setTimeout(() => {
        toastEl.classList.add('hidden');
    }, 4500);
}

// Load and Render Rushs
async function loadRushs() {
    try {
        const res = await fetch(`${API_BASE}/api/rushs`);
        const data = await res.json();
        const rushs = data.rushs || [];
        rushsBadge.textContent = rushs.length;
        if (mobileRushsBadge) mobileRushsBadge.textContent = rushs.length;

        if (rushs.length === 0) {
            rushsGrid.innerHTML = '<div class="loading-state">Aucun rush disponible. Téléversez-en un nouveau ci-dessus !</div>';
            return;
        }

        rushsGrid.innerHTML = '';
        rushs.forEach(rush => {
            const card = document.createElement('div');
            card.className = `rush-card ${selectedRushs.has(rush.relative_path) ? 'selected' : ''}`;
            card.dataset.path = rush.relative_path;

            card.innerHTML = `
                <input type="checkbox" class="rush-checkbox" ${selectedRushs.has(rush.relative_path) ? 'checked' : ''}>
                <button type="button" class="btn-card-delete-rush" data-path="${rush.relative_path}" title="Supprimer ce rush définitivement">✕</button>
                <div class="rush-thumbnail">
                    <video src="${API_BASE}/rushs-media/${encodeURIComponent(rush.relative_path)}" preload="metadata" muted playsinline></video>
                    <span class="rush-meta-pill">${rush.duration}s</span>
                </div>
                <div class="rush-info">
                    <span class="rush-name" title="${rush.name}">${rush.name}</span>
                    <span class="rush-sub">${rush.folder ? rush.folder + ' • ' : ''}${rush.size_mb} Mo</span>
                </div>
            `;

            // Delete action on rush card
            const delBtn = card.querySelector('.btn-card-delete-rush');
            delBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (confirm(`Confirmez-vous la suppression du rush : ${rush.name} ?`)) {
                    await deleteRushFile(rush.relative_path);
                }
            });

            // Toggle selection
            card.addEventListener('click', (e) => {
                if (e.target.tagName.toLowerCase() === 'input' || e.target.classList.contains('btn-card-delete-rush')) return;
                const checkbox = card.querySelector('.rush-checkbox');
                checkbox.checked = !checkbox.checked;
                toggleRushSelection(rush.relative_path, checkbox.checked, card);
            });

            const checkbox = card.querySelector('.rush-checkbox');
            checkbox.addEventListener('change', () => {
                toggleRushSelection(rush.relative_path, checkbox.checked, card);
            });

            rushsGrid.appendChild(card);
        });

        updateSelectionUI();
    } catch (err) {
        console.error('Erreur chargement rushs:', err);
        rushsGrid.innerHTML = '<div class="loading-state">Erreur lors du chargement des rushs.</div>';
    }
}

function toggleRushSelection(path, isSelected, cardElement) {
    if (isSelected) {
        selectedRushs.add(path);
        cardElement.classList.add('selected');
    } else {
        selectedRushs.delete(path);
        cardElement.classList.remove('selected');
    }
    updateSelectionUI();
}

function updateSelectionUI() {
    const count = selectedRushs.size;
    selectedCounter.textContent = `${count} rush${count > 1 ? 's' : ''} sélectionné${count > 1 ? 's' : ''}`;
    btnSubmitMontage.disabled = count === 0;
}

// Drag & Drop Upload
function initDropzone() {
    btnBrowse.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            handleUpload(fileInput.files);
        }
    });

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleUpload(e.dataTransfer.files);
        }
    });
}

async function handleUpload(fileList) {
    const formData = new FormData();
    for (let i = 0; i < fileList.length; i++) {
        formData.append('files', fileList[i]);
    }

    uploadStatus.innerHTML = '<div class="loading-state">Téléversement des fichiers en cours...</div>';

    try {
        const res = await fetch(`${API_BASE}/api/rushs/upload`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        const uploaded = data.uploaded || [];

        // Auto-select uploaded files
        uploaded.forEach(u => selectedRushs.add(u.relative_path));

        showToast(`${uploaded.length} rush(s) téléversé(s) avec succès !`);
        uploadStatus.innerHTML = '';

        // Switch to library view and refresh
        btnShowLibrary.click();
        await loadRushs();
    } catch (err) {
        console.error('Erreur téléversement:', err);
        uploadStatus.innerHTML = '<div class="loading-state" style="color: #ef4444;">Erreur lors du téléversement.</div>';
    }
}

// Form Submission & Polling
function initMontageForm() {
    montageForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (selectedRushs.size === 0) {
            showToast('Veuillez sélectionner au moins un rush.', true);
            return;
        }

        const formData = new FormData(montageForm);
        const burnHookEl = document.getElementById('burn_hook');
        const payload = {
            rush_paths: Array.from(selectedRushs),
            target_duration: parseInt(formData.get('target_duration') || '25'),
            music_choice: formData.get('music_choice') || 'auto',
            custom_hook: formData.get('custom_hook') || '',
            burn_hook: burnHookEl ? Boolean(burnHookEl.checked) : false,
        };

        btnSubmitMontage.disabled = true;
        progressCard.classList.remove('hidden');
        resultCard.classList.add('hidden');
        progressCard.scrollIntoView({ behavior: 'smooth' });

        try {
            const res = await fetch(`${API_BASE}/api/montages/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            currentJobId = data.job_id;

            // Start polling
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(pollJobStatus, 1500);
        } catch (err) {
            console.error('Erreur lancement job:', err);
            showToast('Erreur lors du lancement du montage.', true);
            btnSubmitMontage.disabled = false;
            progressCard.classList.add('hidden');
        }
    });
}

async function pollJobStatus() {
    if (!currentJobId) return;
    try {
        const res = await fetch(`${API_BASE}/api/montages/jobs/${currentJobId}`);
        const job = await res.json();

        progressBarFill.style.width = `${job.progress}%`;
        progressPct.textContent = `${job.progress}%`;
        progressSub.textContent = job.message || 'Traitement en cours...';

        if (job.status === 'done') {
            clearInterval(pollInterval);
            pollInterval = null;
            btnSubmitMontage.disabled = false;
            progressCard.classList.add('hidden');
            displayResult(job.result);
            loadHistory();
            showToast('Montage terminé avec succès !');
        } else if (job.status === 'error') {
            clearInterval(pollInterval);
            pollInterval = null;
            btnSubmitMontage.disabled = false;
            showToast(`Erreur : ${job.error || 'Échec du montage'}`, true);
            progressSub.textContent = `Erreur : ${job.error}`;
        }
    } catch (err) {
        console.error('Erreur polling:', err);
    }
}

// Display Result
function displayResult(result) {
    if (!result) return;
    resultHook.textContent = result.hook || 'MONTAGE FINAL';
    resultDesc.textContent = result.description || 'Description non renseignée';
    resultDuration.textContent = `Durée : ${result.duration}s`;

    resultHashtags.innerHTML = '';
    (result.hashtags || []).forEach(tag => {
        const span = document.createElement('span');
        span.className = 'tag-chip';
        span.textContent = tag;
        resultHashtags.appendChild(span);
    });

    const videoSrc = `${API_BASE}${result.video_url.startsWith('/') ? result.video_url : '/' + result.video_url}`;
    resultVideo.src = videoSrc;
    resultVideo.load();

    btnDownloadResult.href = videoSrc;
    btnDownloadResult.setAttribute('download', result.filename);

    btnSendQueue.onclick = async () => {
        try {
            btnSendQueue.disabled = true;
            btnSendQueue.textContent = 'Transmission en cours...';
            const res = await fetch(`${API_BASE}/api/montages/${result.id}/send-to-queue`, { method: 'POST' });
            const data = await res.json();
            showToast(data.message || 'Vidéo transmise à la file d\'attente !');
        } catch (err) {
            showToast('Erreur transmission vers file d\'attente.', true);
        } finally {
            btnSendQueue.disabled = false;
            btnSendQueue.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
                </svg>
                <span>Envoyer vers la file d'attente (Port 8000)</span>
            `;
        }
    };

    resultCard.classList.remove('hidden');
    resultCard.scrollIntoView({ behavior: 'smooth' });
}

// Load and Render History
async function loadHistory() {
    try {
        const res = await fetch(`${API_BASE}/api/history`);
        const data = await res.json();
        const history = data.history || [];
        historyBadge.textContent = history.length;
        if (mobileHistoryBadge) mobileHistoryBadge.textContent = history.length;

        if (history.length === 0) {
            historyContainer.innerHTML = '<div class="loading-state">Aucun montage réalisé pour le moment.</div>';
            return;
        }

        historyContainer.innerHTML = '';
        history.forEach(item => {
            const card = document.createElement('div');
            card.className = 'history-card';
            const vUrl = `${API_BASE}${item.video_url.startsWith('/') ? item.video_url : '/' + item.video_url}`;
            card.innerHTML = `
                <div class="history-video-thumb">
                    <video src="${vUrl}" controls playsinline preload="metadata"></video>
                </div>
                <div class="history-body">
                    <div class="history-meta">
                        <span>${item.created_at}</span>
                        <span>${item.duration}s</span>
                    </div>
                    <h3 class="history-title">${item.hook || item.filename}</h3>
                    <p style="font-size: 12px; color: #94a3b8; line-height: 1.4;">${item.description || ''}</p>
                    <div class="history-actions">
                        <a href="${vUrl}" download="${item.filename}" class="btn-secondary" style="flex: 1; padding: 8px 10px; font-size: 11px; text-align: center; text-decoration: none;">
                            Télécharger
                        </a>
                        <button class="btn-primary btn-queue-action" data-id="${item.id}" style="flex: 1.5; padding: 8px 10px; font-size: 11px;">
                            Publier (8000)
                        </button>
                        <button class="btn-danger btn-delete-action" data-id="${item.id}">
                            ✕
                        </button>
                    </div>
                </div>
            `;

            // Queue action
            card.querySelector('.btn-queue-action').addEventListener('click', async () => {
                try {
                    const resQ = await fetch(`${API_BASE}/api/montages/${item.id}/send-to-queue`, { method: 'POST' });
                    const resData = await resQ.json();
                    showToast(resData.message || 'Transmis à la file d\'attente !');
                } catch (err) {
                    showToast('Erreur transmission.', true);
                }
            });

            // Delete action
            card.querySelector('.btn-delete-action').addEventListener('click', async () => {
                if (confirm('Voulez-vous supprimer ce montage ?')) {
                    await fetch(`${API_BASE}/api/history/${item.id}`, { method: 'DELETE' });
                    loadHistory();
                    showToast('Montage supprimé.');
                }
            });

            historyContainer.appendChild(card);
        });
    } catch (err) {
        console.error('Erreur chargement historique:', err);
    }
}

// Load and Render Raw Rushs Table
async function loadRawRushsTable() {
    try {
        const res = await fetch(`${API_BASE}/api/rushs`);
        const data = await res.json();
        const rushs = data.rushs || [];

        if (rushs.length === 0) {
            rawRushsContainer.innerHTML = '<div class="loading-state">Aucun rush brut trouvé.</div>';
            return;
        }

        let html = `
            <table class="rushs-table">
                <thead>
                    <tr>
                        <th>Nom du fichier</th>
                        <th>Dossier</th>
                        <th>Durée</th>
                        <th>Taille</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
        `;

        rushs.forEach(r => {
            html += `
                <tr>
                    <td style="font-weight: 700; color: #ffffff;">${r.name}</td>
                    <td>${r.folder || 'Racine'}</td>
                    <td>${r.duration}s</td>
                    <td>${r.size_mb} Mo</td>
                    <td>
                        <div style="display: flex; gap: 8px; align-items: center;">
                            <button class="btn-secondary btn-quick-use" data-path="${r.relative_path}" style="padding: 6px 12px; font-size: 11px;">
                                Utiliser
                            </button>
                            <button class="btn-danger btn-delete-rush" data-path="${r.relative_path}" style="padding: 6px 12px; font-size: 11px;" title="Supprimer ce rush pour libérer de l'espace">
                                Supprimer
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        rawRushsContainer.innerHTML = html;

        rawRushsContainer.querySelectorAll('.btn-quick-use').forEach(btn => {
            btn.addEventListener('click', () => {
                const p = btn.dataset.path;
                selectedRushs.clear();
                selectedRushs.add(p);
                // Switch to Create tab
                switchTab('create');
                loadRushs();
            });
        });

        rawRushsContainer.querySelectorAll('.btn-delete-rush').forEach(btn => {
            btn.addEventListener('click', async () => {
                const p = btn.dataset.path;
                if (confirm(`Confirmez-vous la suppression définitive du rush : ${p} ?`)) {
                    await deleteRushFile(p);
                }
            });
        });
    } catch (err) {
        console.error('Erreur tableau rushs:', err);
    }
}

// Global Delete Rush Function
async function deleteRushFile(relativePath) {
    try {
        const res = await fetch(`${API_BASE}/api/rushs/${encodeURIComponent(relativePath)}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Rush supprimé avec succès.');
            selectedRushs.delete(relativePath);
            loadRushs();
            loadRawRushsTable();
        } else {
            showToast(data.detail || 'Erreur lors de la suppression.', true);
        }
    } catch (err) {
        showToast('Erreur réseau lors de la suppression.', true);
    }
}
