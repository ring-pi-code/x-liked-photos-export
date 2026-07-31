(function () {
    const folderInput = document.getElementById('folder');
    const loadBtn = document.getElementById('loadBtn');
    const durationInput = document.getElementById('duration');
    const stage = document.getElementById('stage');
    const status = document.getElementById('status');
    const playPauseBtn = document.getElementById('playPauseBtn');
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');
    const fullscreenBtn = document.getElementById('fullscreenBtn');
    const shuffleBtn = document.getElementById('shuffleBtn');
    const repeatBtn = document.getElementById('repeatBtn');
    const hideUiBtn = document.getElementById('hideUiBtn');
    const layoutBtns = document.querySelectorAll('.layout-btn');

    const layoutCounts = {
        '1': 1,
        '2h': 2,
        '2v': 2,
        '4': 4,
        '6': 6,
    };

    let images = [];
    let currentIndex = 0;
    let timer = null;
    let isPlaying = false;
    let layout = '1';
    let shuffle = false;
    let repeat = true;
    let imageOrder = [];

    // v2: the v1 key predates the server-side default folder and could
    // hold a stale folder that silently wins over it.
    const STORAGE_KEY = 'pi-slideshow-settings-v2';

    function saveSettings() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                folder: folderInput.value.trim(),
                duration: durationInput.value,
                layout,
                shuffle,
                repeat,
            }));
        } catch (e) { /* storage unavailable; ignore */ }
    }

    function applyLayout(newLayout) {
        layout = newLayout;
        stage.className = `stage layout-${layout}`;
        layoutBtns.forEach((b) => b.classList.toggle('active', b.dataset.layout === layout));
    }

    function applyShuffle(value) {
        shuffle = value;
        shuffleBtn.classList.toggle('active', shuffle);
        shuffleBtn.textContent = `Shuffle: ${shuffle ? 'On' : 'Off'}`;
    }

    function applyRepeat(value) {
        repeat = value;
        repeatBtn.classList.toggle('active', repeat);
        repeatBtn.textContent = `Repeat: ${repeat ? 'On' : 'Off'}`;
    }

    async function restoreSettings() {
        let saved = {};
        try {
            saved = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
        } catch (e) { /* ignore */ }

        let serverFolder = '';
        try {
            const res = await fetch('/api/config');
            serverFolder = (await res.json()).default_folder || '';
        } catch (e) { /* ignore */ }

        // URL param takes precedence, then the saved folder, then the server default
        const params = new URLSearchParams(window.location.search);
        const folder = params.get('folder') || saved.folder || serverFolder || '';
        if (folder) folderInput.value = folder;

        if (saved.duration) durationInput.value = saved.duration;
        if (saved.layout && layoutCounts[saved.layout]) applyLayout(saved.layout);
        if (typeof saved.shuffle === 'boolean') applyShuffle(saved.shuffle);
        if (typeof saved.repeat === 'boolean') applyRepeat(saved.repeat);

        // Auto-load the remembered folder
        if (folderInput.value.trim()) loadImages();
    }

    restoreSettings();

    loadBtn.addEventListener('click', loadImages);
    folderInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') loadImages();
    });

    async function loadImages() {
        const folder = folderInput.value.trim();
        if (!folder) {
            status.textContent = 'Please enter a folder path';
            return;
        }
        status.textContent = 'Loading...';
        try {
            const res = await fetch(`/api/images?folder=${encodeURIComponent(folder)}`);
            const data = await res.json();
            if (data.error) {
                status.textContent = `Error: ${data.error}`;
                return;
            }
            images = data.images;
            currentIndex = 0;
            buildImageOrder();
            status.textContent = `${images.length} images loaded`;
            saveSettings();
            if (images.length > 0) {
                startSlideshow();
            } else {
                stage.innerHTML = '';
                pause();
            }
        } catch (err) {
            status.textContent = `Error: ${err.message}`;
        }
    }

    function buildImageOrder() {
        imageOrder = Array.from({ length: images.length }, (_, i) => i);
        if (shuffle) {
            for (let i = imageOrder.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [imageOrder[i], imageOrder[j]] = [imageOrder[j], imageOrder[i]];
            }
        }
    }

    function getIndices() {
        const count = layoutCounts[layout];
        const indices = [];
        for (let i = 0; i < count; i++) {
            const idx = currentIndex + i;
            if (idx < imageOrder.length) {
                indices.push(imageOrder[idx]);
            } else if (repeat && imageOrder.length > 0) {
                indices.push(imageOrder[idx % imageOrder.length]);
            }
        }
        return indices;
    }

    const FADE_MS = 200;
    let fadeTimer = null;

    function buildStage() {
        const indices = getIndices();
        stage.innerHTML = '';
        indices.forEach((idx) => {
            const img = document.createElement('img');
            img.src = `/api/image?path=${encodeURIComponent(images[idx].path)}`;
            img.alt = images[idx].name;
            img.loading = 'eager';
            img.draggable = false;
            const show = () => requestAnimationFrame(() => img.classList.add('loaded'));
            img.addEventListener('load', show, { once: true });
            img.addEventListener('error', show, { once: true });
            if (img.complete && img.naturalWidth > 0) show();
            stage.appendChild(img);
        });
    }

    function render() {
        if (images.length === 0) {
            if (fadeTimer) {
                clearTimeout(fadeTimer);
                fadeTimer = null;
            }
            stage.innerHTML = '';
            return;
        }
        updateStatusProgress();
        const current = stage.querySelectorAll('img');
        if (current.length === 0) {
            buildStage();
            return;
        }
        // Fade the current images out, then swap in the new ones (they fade
        // in on load). A rapid re-render cancels the pending swap.
        current.forEach((img) => img.classList.add('fade-out'));
        if (fadeTimer) clearTimeout(fadeTimer);
        fadeTimer = setTimeout(() => {
            fadeTimer = null;
            buildStage();
        }, FADE_MS);
    }

    function updateStatusProgress() {
        if (images.length === 0) return;
        const count = layoutCounts[layout];
        const end = Math.min(currentIndex + count, images.length);
        status.textContent = `${images.length} images loaded • showing ${currentIndex + 1}-${end}${isPlaying ? ' • playing' : ' • paused'}`;
    }

    function advance() {
        const count = layoutCounts[layout];
        currentIndex += count;
        if (currentIndex >= images.length) {
            if (repeat) {
                currentIndex = 0;
                if (shuffle) buildImageOrder();
            } else {
                currentIndex = Math.max(0, images.length - count);
                pause();
            }
        }
        render();
    }

    function goBack() {
        const count = layoutCounts[layout];
        currentIndex -= count;
        if (currentIndex < 0) {
            if (repeat) {
                currentIndex = Math.max(0, images.length - count);
            } else {
                currentIndex = 0;
            }
        }
        render();
    }

    function startSlideshow() {
        if (images.length === 0) return;
        render();
        isPlaying = true;
        playPauseBtn.textContent = 'Pause';
        resetTimer();
    }

    function pause() {
        isPlaying = false;
        playPauseBtn.textContent = 'Play';
        if (timer) {
            clearInterval(timer);
            timer = null;
        }
        updateStatusProgress();
    }

    function resetTimer() {
        if (timer) clearInterval(timer);
        if (isPlaying) {
            const seconds = Math.max(1, parseFloat(durationInput.value) || 5);
            timer = setInterval(advance, seconds * 1000);
        }
        updateStatusProgress();
    }

    playPauseBtn.addEventListener('click', () => {
        if (isPlaying) {
            pause();
        } else {
            if (images.length === 0) {
                loadImages();
            } else {
                startSlideshow();
            }
        }
    });

    nextBtn.addEventListener('click', () => {
        advance();
        resetTimer();
    });

    prevBtn.addEventListener('click', () => {
        goBack();
        resetTimer();
    });

    durationInput.addEventListener('change', () => { resetTimer(); saveSettings(); });
    durationInput.addEventListener('input', () => { resetTimer(); saveSettings(); });

    layoutBtns.forEach((btn) => {
        btn.addEventListener('click', () => {
            applyLayout(btn.dataset.layout);
            saveSettings();
            currentIndex = 0;
            render();
            resetTimer();
        });
    });

    shuffleBtn.addEventListener('click', () => {
        applyShuffle(!shuffle);
        saveSettings();
        buildImageOrder();
        currentIndex = 0;
        render();
    });

    repeatBtn.addEventListener('click', () => {
        applyRepeat(!repeat);
        saveSettings();
    });

    fullscreenBtn.addEventListener('click', () => {
        if (document.fullscreenElement) {
            document.exitFullscreen();
        } else {
            document.documentElement.requestFullscreen().catch(() => {});
        }
    });

    hideUiBtn.addEventListener('click', () => {
        document.body.classList.add('hide-ui');
        resetIdleTimer();
    });

    // Fade the hint and mouse cursor after a few seconds without mouse
    // movement, whenever the UI is hidden.
    const IDLE_MS = 3000;
    let idleTimer = null;

    function clearIdle() {
        document.body.classList.remove('idle');
        if (idleTimer) {
            clearTimeout(idleTimer);
            idleTimer = null;
        }
    }

    function resetIdleTimer() {
        clearIdle();
        idleTimer = setTimeout(() => {
            if (document.body.classList.contains('hide-ui')) {
                document.body.classList.add('idle');
            }
        }, IDLE_MS);
    }

    document.addEventListener('mousemove', resetIdleTimer);

    document.addEventListener('fullscreenchange', () => {
        if (document.fullscreenElement) {
            fullscreenBtn.textContent = 'Exit Full Screen';
        } else {
            fullscreenBtn.textContent = '⛶ Full Screen';
            clearIdle();
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === ' ') {
            e.preventDefault();
            playPauseBtn.click();
        } else if (e.key === 'ArrowRight') {
            nextBtn.click();
        } else if (e.key === 'ArrowLeft') {
            prevBtn.click();
        } else if (e.key === 'f' || e.key === 'F') {
            fullscreenBtn.click();
        } else if (e.key === 'h' || e.key === 'H') {
            document.body.classList.toggle('hide-ui');
            resetIdleTimer();
        } else if (e.key === 'Escape') {
            document.body.classList.remove('hide-ui');
            clearIdle();
        }
    });
})();
