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
    let visibilityChanges = 0;
    
    // Global screen stream video element
    const screenVideo = document.createElement('video');
    screenVideo.style.position = 'fixed';
    screenVideo.style.top = '-9999px';
    screenVideo.style.opacity = '0';
    screenVideo.autoplay = true;
    screenVideo.muted = true;
    document.body.appendChild(screenVideo);

    // Define a function for screen monitoring to allow restarting
    function startScreenMonitoring() {
        navigator.mediaDevices.getDisplayMedia({ video: true })
            .then(stream => {
                const track = stream.getVideoTracks()[0];
                const settings = track.getSettings();
                
                if (settings.displaySurface && settings.displaySurface !== 'monitor') {
                    alert("Please select Entire Screen to continue the exam");
                    track.stop();
                    startScreenMonitoring();
                    return;
                }

                screenVideo.srcObject = stream;
                screenVideo.play();
                
                // Detect when screen sharing is stopped by the user
                track.onended = () => {
                    const wantsToContinue = confirm("If you stop screen sharing, your exam will be terminated.\n\nClick 'OK' to restart screen sharing and continue, or 'Cancel' to terminate the exam.");
                    if (wantsToContinue) {
                        startScreenMonitoring();
                    } else {
                        alert("Screen sharing stopped. Exam terminated.");
                        if (form) {
                            form.submit();
                        } else {
                            window.location.href = '/student/dashboard';
                        }
                    }
                };
            })
            .catch(err => {
                console.warn("Screen sharing permission denied or failed:", err);
                alert("CRITICAL: Screen sharing permission is required to take this exam.");
                if (form && screenVideo.srcObject) {
                    form.submit();
                } else {
                    window.location.href = '/student/dashboard';
                }
            });
    }

    // Start it initially
    startScreenMonitoring();

    // Warn when tab is switched or minimized
    let tabSwitchTimeout = null;
    let isTabActive = true;
    let isRecordingVideo = false;
    
    document.addEventListener('visibilitychange', () => {
        isTabActive = (document.visibilityState === 'visible');
        if (document.visibilityState === 'hidden') {
            
            // Start video recording from active stream instead of screenshot
            if (screenVideo.srcObject && screenVideo.readyState >= 2 && !isRecordingVideo) {
                try {
                    isRecordingVideo = true;
                    // Start screen recording
                    const mediaRecorder = new MediaRecorder(screenVideo.srcObject, { mimeType: 'video/webm' });
                    const recordedChunks = [];
                    
                    mediaRecorder.ondataavailable = (e) => {
                        if (e.data.size > 0) {
                            recordedChunks.push(e.data);
                        }
                    };
                    
                    mediaRecorder.onstop = () => {
                        isRecordingVideo = false;
                        const blob = new Blob(recordedChunks, { type: 'video/webm' });
                        const formData = new FormData();
                        formData.append('video', blob, 'cheating.webm');
                        if (examId) {
                            formData.append('exam_id', examId);
                        }
                        
                        // Send video via FormData to the new endpoint
                        fetch('/upload-cheating-video', {
                            method: 'POST',
                            body: formData
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.status === 'alert_recorded') {
                                showWarning("Notice: " + data.type);
                            }
                        })
                        .catch(e => console.error("Error uploading video:", e));
                    };
                    
                    mediaRecorder.start();
                    
                    // Stop recording after 6 seconds
                    setTimeout(() => {
                        if (mediaRecorder.state === 'recording') {
                            mediaRecorder.stop();
                        }
                    }, 6000);
                } catch (e) {
                    console.error("Failed to start MediaRecorder:", e);
                    isRecordingVideo = false;
                }
            }

            tabSwitchTimeout = setTimeout(() => {
                visibilityChanges++;
                showWarning(`Warning: You have left the exam tab. (${visibilityChanges}/3 allowed)`);
                
                if (visibilityChanges >= 3) {
                    alert("Exam terminated due to multiple tab switches.");
                    if (form) form.submit();
                    else window.location.href = '/student/dashboard';
                }
            }, 1000);
        } else if (document.visibilityState === 'visible') {
            if (tabSwitchTimeout) {
                clearTimeout(tabSwitchTimeout);
                tabSwitchTimeout = null;
            }
        }
    });

    // Real camera feed setup mapping to the aside view
    const video = document.getElementById('webcam');
    const overlay = document.getElementById('videoOverlay');
    if (!video) return;
    
    // Canvas for capturing frames
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    
    // Audio Context for Microphone Level Monitoring
    let audioContext;
    let analyser;
    let microphone;
    let javascriptNode;
    
    navigator.mediaDevices.getUserMedia({ video: true, audio: true })
        .then(stream => {
            // Video display logic
            video.srcObject = stream;
            video.style.display = 'block';
            if (overlay) overlay.style.display = 'none';
            
            // Audio setup logic
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioContext.createAnalyser();
            microphone = audioContext.createMediaStreamSource(stream);
            javascriptNode = audioContext.createScriptProcessor(2048, 1, 1);
            
            analyser.smoothingTimeConstant = 0.8;
            analyser.fftSize = 1024;
            
            microphone.connect(analyser);
            analyser.connect(javascriptNode);
            javascriptNode.connect(audioContext.destination);
            
            let isRecordingAudio = false;
            let audioRecorder = null;
            let audioChunks = [];
            let silenceTimer = null;
            
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
                    if (!isRecordingAudio) {
                        isRecordingAudio = true;
                        audioChunks = [];
                        try {
                            const audioStream = new MediaStream([stream.getAudioTracks()[0]]);
                            audioRecorder = new MediaRecorder(audioStream, { mimeType: 'audio/webm' });
                        } catch (e) {
                            const audioStream = new MediaStream([stream.getAudioTracks()[0]]);
                            audioRecorder = new MediaRecorder(audioStream);
                        }
                        
                        audioRecorder.ondataavailable = e => {
                            if (e.data.size > 0) audioChunks.push(e.data);
                        };
                        
                        audioRecorder.onstop = () => {
                            isRecordingAudio = false;
                            const blob = new Blob(audioChunks, { type: 'audio/webm' });
                            
                            if (blob.size > 0) {
                                const formData = new FormData();
                                formData.append('audio', blob, 'cheating.webm');
                                if (examId) formData.append('exam_id', examId);
                                
                                fetch('/upload-cheating-audio', {
                                    method: 'POST',
                                    body: formData
                                })
                                .then(response => response.json())
                                .then(data => {
                                    if (data.status === 'alert_recorded') {
                                        showWarning("Notice: " + data.type);
                                    }
                                })
                                .catch(e => console.error("Error uploading audio:", e));
                            } else {
                                console.warn("Recorded audio blob is empty, not uploading.");
                            }
                        };
                        
                        audioRecorder.start();
                    }
                    
                    if (silenceTimer) {
                        clearTimeout(silenceTimer);
                        silenceTimer = null;
                    }
                } else {
                    if (isRecordingAudio && !silenceTimer) {
                        // Wait for 3 seconds of continuous silence before stopping
                        silenceTimer = setTimeout(() => {
                            if (audioRecorder && audioRecorder.state === 'recording') {
                                audioRecorder.stop();
                            }
                            silenceTimer = null;
                        }, 3000);
                    }
                }
            }
            
            // Start physical frame capture loop (every 5 seconds)
            video.onloadedmetadata = () => {
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                
                setInterval(() => {
                    if (!isTabActive) return; // Pause face detection when tab is hidden
                    
                    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                    const imageData = canvas.toDataURL('image/jpeg', 0.8);
                    
                    fetch('/upload_frame', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ image: imageData, exam_id: examId })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'alert_recorded') {
                            showWarning("Notice: " + data.type);
                        }
                    })
                    .catch(error => console.error('Error uploading frame:', error));
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
