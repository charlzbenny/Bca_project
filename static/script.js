document.addEventListener('DOMContentLoaded', () => {
    // Check if on exam page
    if (document.querySelector('.exam-container')) {
        initExamFeatures();
        initProctoring();
    }
});

function initExamFeatures() {
    const form = document.getElementById('examForm');
    if (!form) return;
    
    // Exam Timer
    const durationMins = parseInt(form.getAttribute('data-duration') || '60');
    let timeLeft = durationMins * 60;
    const timeDisplay = document.getElementById('timeDisplay');
    
    const timerInterval = setInterval(() => {
        timeLeft--;
        const m = Math.floor(timeLeft / 60);
        const s = timeLeft % 60;
        timeDisplay.textContent = `${m}:${s.toString().padStart(2, '0')}`;
        
        if (timeLeft <= 300) { // 5 mins
            document.getElementById('timer').style.color = 'var(--danger)';
        }
        
        if (timeLeft <= 0) {
            clearInterval(timerInterval);
            form.submit();
        }
    }, 1000);
    
    // Pagination Logic
    const pages = document.querySelectorAll('.question-page');
    let currentPageIndex = 0;
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');
    const submitBtn = document.getElementById('submitBtn');
    const qCountText = document.getElementById('qCountText');
    const totalPages = pages.length;
    
    function updatePagination() {
        pages.forEach((p, i) => {
            p.style.display = (i === currentPageIndex) ? 'block' : 'none';
        });
        
        qCountText.textContent = `Question ${currentPageIndex + 1} of ${totalPages}`;
        
        if (currentPageIndex === 0) {
            prevBtn.style.display = 'none';
        } else {
            prevBtn.style.display = 'inline-block';
        }
        
        if (currentPageIndex === totalPages - 1) {
            nextBtn.style.display = 'none';
            submitBtn.style.display = 'inline-block';
        } else {
            nextBtn.style.display = 'inline-block';
            submitBtn.style.display = 'none';
        }
    }
    
    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            if (currentPageIndex < totalPages - 1) {
                currentPageIndex++;
                updatePagination();
            }
        });
    }
    
    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            if (currentPageIndex > 0) {
                currentPageIndex--;
                updatePagination();
            }
        });
    }
}

function initProctoring() {
    const form = document.getElementById('examForm');
    const examId = form ? form.getAttribute('data-exam-id') : null;
    let tabSwitchCount = 0;
    // Audio Context for Microphone Level Monitoring and Recording
    let audioContext;
    let analyser;
    let microphone;
    let javascriptNode;
    let mediaRecorder;
    let audioChunks = [];
    let isRecordingAudio = false;
    
    // Unified function to send alert payload including base64 audio
    function sendAlertData(alertType, value) {
        let payload = { exam_id: examId };
        
        if (alertType === 'tab_switch') payload.tab_switch = true;
        if (alertType === 'audio_level') payload.audio_level = value;
        if (alertType === 'image') payload.image = value;
        
        // If we have an active MediaRecorder, grab whatever chunks we have to send alongside
        if (mediaRecorder && mediaRecorder.state !== 'inactive' && audioChunks.length > 0) {
            // Take the last few chunks (giving us recent context) and clear
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            
            const reader = new FileReader();
            reader.readAsDataURL(audioBlob);
            reader.onloadend = function() {
                payload.audio_data = reader.result;
                // Dispatch the fetch now that we have base64 audio
                dispatchUpload(payload);
            };
            
            // Clear chunks so the rolling window resets
            audioChunks = [];
        } else {
            // Just send without audio
            dispatchUpload(payload);
        }
    }
    
    function dispatchUpload(payload) {
        fetch('/upload_frame', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'alert_recorded' && payload.image) {
                // Only show visual warning banner for visual flags (prevent spam)
                showWarning("Notice: " + data.type);
            }
        })
        .catch(e => console.error(e));
    }
    
    // Override the previous visibility listener to use sendAlertData
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
            visibilityTimeout = setTimeout(() => {
                tabSwitchCount++;
                showWarning(`⚠ Tab switching detected. Please stay on the exam page. (${tabSwitchCount}/3 allowed)`);
                
                sendAlertData('tab_switch', true);
                
                if (tabSwitchCount >= 3) {
                    alert("Exam terminated due to multiple tab switches.");
                    if (form) form.submit();
                    else window.location.href = '/student/dashboard';
                }
            }, 1000);
        } else if (document.visibilityState === 'visible') {
            if (visibilityTimeout) {
                clearTimeout(visibilityTimeout);
                visibilityTimeout = null;
            }
        }
    });

    navigator.mediaDevices.getUserMedia({ video: true, audio: true })
        .then(stream => {
            // Video display logic
            video.srcObject = stream;
            video.style.display = 'block';
            if (overlay) overlay.style.display = 'none';
            
            // Audio Level Monitoring Logic
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioContext.createAnalyser();
            microphone = audioContext.createMediaStreamSource(stream);
            javascriptNode = audioContext.createScriptProcessor(2048, 1, 1);
            
            analyser.smoothingTimeConstant = 0.8;
            analyser.fftSize = 1024;
            
            microphone.connect(analyser);
            analyser.connect(javascriptNode);
            javascriptNode.connect(audioContext.destination);
            
            // Audio Recording Logic
            try {
                mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
            } catch (e) {
                console.warn('audio/webm formulation not supported on this browser, falling back to default.');
                mediaRecorder = new MediaRecorder(stream);
            }
            
            mediaRecorder.ondataavailable = function(e) {
                if (e.data.size > 0) {
                    audioChunks.push(e.data);
                    // Keep buffer tight roughly last 10 seconds (assuming 1s chunks)
                    if (audioChunks.length > 10) {
                        audioChunks.shift(); 
                    }
                }
            };
            
            // Start recording requesting data every 1 second
            mediaRecorder.start(1000);
            
            let audioTriggerTimeout = null;
            
            javascriptNode.onaudioprocess = function() {
                var array = new Uint8Array(analyser.frequencyBinCount);
                analyser.getByteFrequencyData(array);
                var values = 0;
                var length = array.length;
                for (var i = 0; i < length; i++) {
                    values += (array[i]);
                }
                var average = values / length;
                
                // If audio volume exceeds threshold
                if (average > 40) { 
                    if (!audioTriggerTimeout) {
                        // Debounce audio triggers so we don't spam the endpoint every millisecond
                        audioTriggerTimeout = setTimeout(() => {
                            sendAlertData('audio_level', average);
                            audioTriggerTimeout = null;
                        }, 5000); 
                    }
                }
            }
            
            // Start physical frame capture loop (every 5 seconds)
            video.onloadedmetadata = () => {
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                
                setInterval(() => {
                    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                    const imageData = canvas.toDataURL('image/jpeg', 0.8);
                    
                    sendAlertData('image', imageData);
                }, 5000); // Check visual every 5s
            };
        })
        .catch(err => {
            console.error("Camera/Mic access denied or error:", err);
            alert("CRITICAL: Camera and Microphone access is required for this exam. Please enable permissions and refresh the page.");
        });
}

function showWarning(message) {
    let alertBanner = document.getElementById('alert-banner');
    if (!alertBanner) return;
    
    alertBanner.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${message}`;
    alertBanner.style.display = 'block';
    
    setTimeout(() => {
        alertBanner.style.display = 'none';
    }, 6000);
}
