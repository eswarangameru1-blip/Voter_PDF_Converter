document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const cardUpload = document.getElementById("card-upload");
    const cardProgress = document.getElementById("card-progress");
    const cardResult = document.getElementById("card-result");
    const cardError = document.getElementById("card-error");

    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const btnBrowse = document.getElementById("btn-browse");
    const fileDetails = document.getElementById("file-details");
    const selectedFilename = document.getElementById("selected-filename");
    const selectedFilesize = document.getElementById("selected-filesize");
    const btnRemoveFile = document.getElementById("btn-remove-file");
    const btnStartConvert = document.getElementById("btn-start-convert");

    const progressStage = document.getElementById("progress-stage");
    const progressRecords = document.getElementById("progress-records");
    const progressPages = document.getElementById("progress-pages");
    const progressTime = document.getElementById("progress-time");
    const progressBarFill = document.getElementById("progress-bar-fill");
    const progressPercentLabel = document.getElementById("progress-percent-label");
    const progressOcrStatus = document.getElementById("progress-ocr-status");
    const btnCancelConversion = document.getElementById("btn-cancel-conversion");

    const resTotal = document.getElementById("res-total");
    const resDuplicates = document.getElementById("res-duplicates");
    const resInvalid = document.getElementById("res-invalid");
    const resDuration = document.getElementById("res-duration");
    const resultWarningAlert = document.getElementById("result-warning-alert");
    const resultWarningText = document.getElementById("result-warning-text");
    const btnDownloadExcel = document.getElementById("btn-download-excel");
    const btnConvertAnother = document.getElementById("btn-convert-another");

    const errorMessageText = document.getElementById("error-message-text");
    const btnErrorRetry = document.getElementById("btn-error-retry");
    const btnErrorDismiss = document.getElementById("btn-error-dismiss");

    const btnSettingsToggle = document.getElementById("btn-settings-toggle");
    const btnCloseSettings = document.getElementById("btn-close-settings");
    const modalSettings = document.getElementById("modal-settings");
    const btnSaveSettings = document.getElementById("btn-save-settings");

    const btnHistoryToggle = document.getElementById("btn-history-toggle");
    const btnCloseHistory = document.getElementById("btn-close-history");
    const sidebarHistory = document.getElementById("sidebar-history");
    const historyItemsContainer = document.getElementById("history-items-container");

    // Local state variables
    let selectedFile = null;
    let pollInterval = null;
    let activeTaskId = null;
    let startTime = null;
    let activeExcelB64 = null;
    let activeFilename = null;

    function triggerExcelDownload(taskId) {
        if (activeExcelB64) {
            try {
                const byteCharacters = atob(activeExcelB64);
                const byteNumbers = new Array(byteCharacters.length);
                for (let i = 0; i < byteCharacters.length; i++) {
                    byteNumbers[i] = byteCharacters.charCodeAt(i);
                }
                const byteArray = new Uint8Array(byteNumbers);
                const blob = new Blob([byteArray], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                let dlName = activeFilename || "voter_details.xlsx";
                if (!dlName.endsWith(".xlsx")) dlName += ".xlsx";
                a.download = dlName;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                setTimeout(() => URL.revokeObjectURL(url), 1000);
                return;
            } catch (err) {
                console.error("Client-side Base64 download error, using endpoint:", err);
            }
        }
        window.location.href = `/api/download/${taskId}`;
    }

    // Load persisted settings on launch
    loadSettings();
    fetchHistory();

    // Theme Toggle Handler
    document.getElementById("setting-theme").addEventListener("change", (e) => {
        setTheme(e.target.value);
    });

    function setTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("voter-converter-theme", theme);
    }

    function loadSettings() {
        const theme = localStorage.getItem("voter-converter-theme") || "dark";
        document.getElementById("setting-theme").value = theme;
        setTheme(theme);

        const ocrEnabled = localStorage.getItem("voter-converter-ocr-enabled") !== "false";
        document.getElementById("setting-ocr-enabled").checked = ocrEnabled;

        const ocrEngine = localStorage.getItem("voter-converter-ocr-engine") || "paddle_dynamic";
        document.getElementById("setting-ocr-engine").value = ocrEngine;

        const autoDetect = localStorage.getItem("voter-converter-auto-detect") !== "false";
        document.getElementById("setting-auto-detect").checked = autoDetect;

        const exportFormat = localStorage.getItem("voter-converter-export-format") || "xlsx";
        document.getElementById("setting-export-format").value = exportFormat;
    }

    function saveSettings() {
        localStorage.setItem("voter-converter-ocr-enabled", document.getElementById("setting-ocr-enabled").checked);
        localStorage.setItem("voter-converter-ocr-engine", document.getElementById("setting-ocr-engine").value);
        localStorage.setItem("voter-converter-auto-detect", document.getElementById("setting-auto-detect").checked);
        localStorage.setItem("voter-converter-export-format", document.getElementById("setting-export-format").value);
        
        modalSettings.style.display = "none";
        showToast("Settings applied successfully!");
    }

    // Drag & Drop Handlers
    dropZone.addEventListener("click", () => fileInput.click());
    btnBrowse.addEventListener("click", (e) => {
        e.stopPropagation();
        fileInput.click();
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("dragover");
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            handleFileSelect(e.dataTransfer.files[0]);
        }
    });

    function handleFileSelect(file) {
        // Validate PDF extension
        if (!file.name.toLowerCase().endswith(".pdf") && file.type !== "application/pdf") {
            showToast("Error: Only PDF documents are supported.", "danger");
            return;
        }

        // Validate File Size (100MB)
        const maxSizeBytes = 100 * 1024 * 1024;
        if (file.size > maxSizeBytes) {
            showToast("Error: Maximum file size limit is 100MB.", "danger");
            return;
        }

        selectedFile = file;
        selectedFilename.textContent = file.name;
        selectedFilesize.textContent = formatBytes(file.size);
        
        dropZone.style.display = "none";
        fileDetails.style.display = "flex";
        btnStartConvert.removeAttribute("disabled");
    }

    btnRemoveFile.addEventListener("click", () => {
        resetUploadCard();
    });

    function resetUploadCard() {
        selectedFile = null;
        activeExcelB64 = null;
        activeFilename = null;
        fileInput.value = "";
        dropZone.style.display = "flex";
        fileDetails.style.display = "none";
        btnStartConvert.setAttribute("disabled", "true");
    }

    // Modal Settings Toggles
    btnSettingsToggle.addEventListener("click", () => modalSettings.style.display = "flex");
    btnCloseSettings.addEventListener("click", () => modalSettings.style.display = "none");
    btnSaveSettings.addEventListener("click", saveSettings);
    
    // Sidebar History Toggles
    btnHistoryToggle.addEventListener("click", () => sidebarHistory.classList.add("active"));
    btnCloseHistory.addEventListener("click", () => sidebarHistory.classList.remove("active"));

    // Upload & Convert
    btnStartConvert.addEventListener("click", () => {
        if (!selectedFile) return;

        activeExcelB64 = null;
        activeFilename = null;

        const formData = new FormData();
        formData.append("file", selectedFile);
        
        // Pass pipeline configs
        formData.append("ocr_enabled", document.getElementById("setting-ocr-enabled").checked);
        formData.append("ocr_engine", document.getElementById("setting-ocr-engine").value);
        formData.append("auto_detect", document.getElementById("setting-auto-detect").checked);
        formData.append("export_format", document.getElementById("setting-export-format").value);

        showCard(cardProgress);
        progressStage.textContent = "Uploading roll...";
        progressBarFill.style.width = "0%";
        progressPercentLabel.textContent = "0% Complete";
        progressRecords.textContent = "0";
        progressPages.textContent = "Calculating...";
        progressTime.textContent = "0s";
        progressOcrStatus.innerHTML = `<i class="fa-solid fa-circle-nodes"></i> Waiting...`;

        startTime = Date.now();

        fetch("/api/upload", {
            method: "POST",
            body: formData
        })
        .then(res => {
            if (!res.ok) {
                return res.json().then(err => { throw new Error(err.detail || "Server upload failed"); });
            }
            return res.json();
        })
        .then(data => {
            activeTaskId = data.task_id;
            if (data.excel_b64) {
                activeExcelB64 = data.excel_b64;
            }
            if (data.filename) {
                activeFilename = data.filename.replace(/\.pdf$/i, "") + "_voter_details.xlsx";
            }
            if (data.status === "completed") {
                showSuccess(data, data.task_id);
            } else {
                startPolling(data.task_id);
            }
        })
        .catch(err => {
            showError(err.message);
        });
    });

    // Cancel Job Action
    btnCancelConversion.addEventListener("click", () => {
        stopPolling();
        resetUploadCard();
        showCard(cardUpload);
        showToast("Pipeline conversion cancelled by user.", "warning");
    });

    // Polling Loop
    function startPolling(taskId) {
        if (pollInterval) clearInterval(pollInterval);
        
        pollInterval = setInterval(() => {
            fetch(`/api/status/${taskId}`)
            .then(res => {
                if (!res.ok) throw new Error("Status fetch failed");
                return res.json();
            })
            .then(data => {
                // Update Progress GUI
                progressStage.textContent = data.stage || data.status;
                progressRecords.textContent = data.records_found || 0;
                progressPages.textContent = `${data.current_page} / ${data.total_pages}`;
                
                // Formulate active duration
                let elapsed = Math.round((Date.now() - startTime) / 1000);
                progressTime.textContent = `${elapsed}s`;
                
                progressBarFill.style.width = `${data.progress}%`;
                progressPercentLabel.textContent = `${data.progress}% Complete`;

                // Update OCR tags
                if (data.stage && data.stage.toLowerCase().includes("ocr")) {
                    progressOcrStatus.innerHTML = `<i class="fa-solid fa-microchip animate-pulse"></i> Running OCRFallback`;
                    progressOcrStatus.style.background = "rgba(245, 158, 11, 0.15)";
                    progressOcrStatus.style.borderColor = "rgba(245, 158, 11, 0.25)";
                    progressOcrStatus.style.color = "#fcd34d";
                } else {
                    progressOcrStatus.innerHTML = `<i class="fa-solid fa-circle-nodes"></i> PyMuPDF Text Grid`;
                    progressOcrStatus.style.background = "rgba(99, 102, 241, 0.15)";
                    progressOcrStatus.style.borderColor = "rgba(99, 102, 241, 0.25)";
                    progressOcrStatus.style.color = "#a5b4fc";
                }

                // Check termination conditions
                if (data.status === "completed") {
                    stopPolling();
                    showSuccess(data, taskId);
                } else if (data.status === "failed") {
                    stopPolling();
                    showError(data.error || "A processing exception occurred.");
                }
            })
            .catch(err => {
                stopPolling();
                showError("Lost communication with FastAPI background daemon.");
            });
        }, 1000);
    }

    function stopPolling() {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    }

    // Success View
    function showSuccess(data, taskId) {
        if (data.excel_b64) {
            activeExcelB64 = data.excel_b64;
        }
        if (data.filename) {
            activeFilename = data.filename.replace(/\.pdf$/i, "") + "_voter_details.xlsx";
        }

        const totalRecs = (data.records_found !== undefined && data.records_found !== null) 
            ? data.records_found 
            : ((data.voter_count !== undefined && data.voter_count !== null) ? data.voter_count : 0);

        resTotal.textContent = totalRecs;
        resDuplicates.textContent = data.duplicates_removed !== undefined ? data.duplicates_removed : 0;
        resInvalid.textContent = data.invalid_records !== undefined ? data.invalid_records : 0;
        
        let elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        resDuration.textContent = `${elapsed}s`;

        // Handle Mismatch Warning Box
        if (data.warning) {
            resultWarningText.textContent = data.warning;
            resultWarningAlert.style.display = "flex";
        } else {
            resultWarningAlert.style.display = "none";
        }

        // Hook download trigger
        btnDownloadExcel.onclick = () => {
            triggerExcelDownload(taskId);
        };

        showCard(cardResult);
        fetchHistory();

        // Automatic Download
        setTimeout(() => {
            triggerExcelDownload(taskId);
        }, 800);
    }

    btnConvertAnother.addEventListener("click", () => {
        resetUploadCard();
        showCard(cardUpload);
    });

    // Error View
    function showError(msg) {
        errorMessageText.textContent = msg;
        showCard(cardError);
    }

    btnErrorRetry.addEventListener("click", () => {
        showCard(cardUpload);
        if (selectedFile) {
            btnStartConvert.click();
        }
    });

    btnErrorDismiss.addEventListener("click", () => {
        resetUploadCard();
        showCard(cardUpload);
    });

    // Utility Helpers
    function showCard(card) {
        const cards = [cardUpload, cardProgress, cardResult, cardError];
        cards.forEach(c => {
            c.style.display = "none";
            c.classList.remove("active");
        });
        card.style.display = "block";
        setTimeout(() => card.classList.add("active"), 10);
    }

    function formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return "0 Bytes";
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ["Bytes", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
    }

    // Conversion History List
    function fetchHistory() {
        fetch("/api/history")
        .then(res => res.json())
        .then(data => {
            if (data && data.length > 0) {
                historyItemsContainer.innerHTML = "";
                data.forEach(item => {
                    const li = document.createElement("li");
                    li.className = "history-item";
                    
                    const dateStr = formatDate(item.date);
                    
                    li.innerHTML = `
                        <div class="hist-main-row">
                            <span class="hist-name" title="${item.filename}">${item.filename}</span>
                            <button class="btn-download-again" data-id="${item.task_id}" title="Download Again">
                                <i class="fa-solid fa-cloud-arrow-down"></i>
                            </button>
                        </div>
                        <div class="hist-sub-row">
                            <span>${dateStr}</span>
                            <span><strong>${item.voter_count}</strong> records</span>
                        </div>
                    `;
                    historyItemsContainer.appendChild(li);
                });

                // Attach historical action events
                document.querySelectorAll(".btn-download-again").forEach(btn => {
                    btn.addEventListener("click", (e) => {
                        const taskId = btn.getAttribute("data-id");
                        window.location.href = `/api/download/${taskId}`;
                    });
                });
            } else {
                showEmptyHistory();
            }
        })
        .catch(() => {
            showEmptyHistory();
        });
    }

    function showEmptyHistory() {
        historyItemsContainer.innerHTML = `
            <div class="empty-state-text">
                <i class="fa-regular fa-folder-open"></i>
                <p>No recent conversions found</p>
            </div>
        `;
    }

    function formatDate(dateStr) {
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        } catch {
            return dateStr;
        }
    }

    // Generic Toast Notification
    function showToast(message, type = "success") {
        const toast = document.createElement("div");
        toast.className = `toast-popup toast-${type}`;
        
        let icon = "fa-circle-check";
        if (type === "warning") icon = "fa-circle-exclamation";
        if (type === "danger") icon = "fa-circle-xmark";

        toast.innerHTML = `
            <i class="fa-solid ${icon}"></i>
            <span>${message}</span>
        `;
        document.body.appendChild(toast);

        // Slide in
        setTimeout(() => toast.classList.add("visible"), 10);
        
        // Remove after 3s
        setTimeout(() => {
            toast.classList.remove("visible");
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // CSS inject for Toast to keep all styling localized
    const style = document.createElement("style");
    style.innerHTML = `
        .toast-popup {
            position: fixed;
            bottom: 2rem;
            left: 50%;
            transform: translate(-50%, 40px);
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid var(--card-border);
            backdrop-filter: blur(12px);
            padding: 0.75rem 1.5rem;
            border-radius: 30px;
            color: white;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.9rem;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.3s, transform 0.3s cubic-bezier(0.1, 0.8, 0.2, 1.1);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        .toast-popup.visible {
            opacity: 1;
            transform: translate(-50%, 0);
        }
        .toast-success i { color: var(--success-color); }
        .toast-warning i { color: var(--warning-color); }
        .toast-danger i { color: var(--danger-color); }
    `;
    document.head.appendChild(style);
});

// Polyfill string endswith since we are in ES6 environment
if (!String.prototype.endswith) {
    String.prototype.endswith = function(suffix) {
        return this.indexOf(suffix, this.length - suffix.length) !== -1;
    };
}
