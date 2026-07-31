(function () {
    const folderInput = document.getElementById('folder');
    const sortInput = document.getElementById('sort');
    const fromInput = document.getElementById('from');
    const toInput = document.getElementById('to');
    const applyBtn = document.getElementById('applyBtn');
    const status = document.getElementById('status');
    const timeline = document.getElementById('timeline');
    const sentinel = document.getElementById('sentinel');

    const PAGE_SIZE = 50;
    const STORAGE_KEY = 'pi-slideshow-timeline-settings';

    let offset = 0;
    let total = null;
    let loading = false;
    let done = false;

    function saveSettings() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                folder: folderInput.value.trim(),
                sort: sortInput.value,
                from: fromInput.value,
                to: toInput.value,
            }));
        } catch (e) { /* storage unavailable; ignore */ }
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
        folderInput.value = params.get('folder') || saved.folder || serverFolder || '';
        if (saved.sort) sortInput.value = saved.sort;
        if (saved.from) fromInput.value = saved.from;
        if (saved.to) toInput.value = saved.to;

        reload();
    }

    function queryString() {
        const params = new URLSearchParams({
            folder: folderInput.value.trim(),
            sort: sortInput.value,
            offset: String(offset),
            limit: String(PAGE_SIZE),
        });
        if (fromInput.value) params.set('from', fromInput.value);
        if (toInput.value) params.set('to', toInput.value);
        return params;
    }

    async function loadPage() {
        if (loading || done) return;
        if (!folderInput.value.trim()) {
            status.textContent = 'Enter a folder to load';
            return;
        }
        loading = true;
        status.textContent = 'Loading…';
        try {
            const res = await fetch(`/api/posts?${queryString()}`);
            const data = await res.json();
            if (data.error) {
                status.textContent = `Error: ${data.error}`;
                done = true;
                return;
            }
            total = data.total;
            data.posts.forEach((post) => timeline.appendChild(renderPost(post)));
            offset += data.posts.length;
            if (offset >= total || data.posts.length === 0) done = true;
            status.textContent = total === 0 ? 'No posts found' : `Showing ${offset} of ${total} posts`;
            saveSettings();
        } catch (err) {
            status.textContent = `Error: ${err.message}`;
        } finally {
            loading = false;
        }
    }

    function reload() {
        timeline.innerHTML = '';
        offset = 0;
        total = null;
        done = false;
        loadPage();
    }

    function formatDate(iso) {
        const d = new Date(iso);
        if (isNaN(d)) return iso;
        const date = d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
        const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
        return `${date}, ${time}`;
    }

    function renderPost(post) {
        const card = document.createElement('article');
        card.className = 'post';

        const header = document.createElement('div');
        header.className = 'post-header';
        const author = document.createElement('span');
        author.className = 'post-author';
        author.textContent = post.author || 'Unknown';
        const handle = document.createElement('span');
        handle.className = 'post-handle';
        handle.textContent = post.handle ? `@${post.handle}` : '';
        const date = document.createElement('span');
        date.className = 'post-date';
        date.textContent = `· ${formatDate(post.date)}`;
        header.append(author, handle, date);
        card.appendChild(header);

        if (post.text) {
            const text = document.createElement('div');
            text.className = 'post-text';
            text.textContent = post.text;
            card.appendChild(text);
        }

        if (post.media.length > 0) {
            const media = document.createElement('div');
            media.className = `post-media count-${Math.min(post.media.length, 4)}`;
            post.media.forEach((tile) => {
                if (tile.kind === 'image') {
                    const img = document.createElement('img');
                    img.className = 'media-tile';
                    img.src = `/api/image?path=${encodeURIComponent(tile.path)}`;
                    img.alt = tile.name;
                    img.loading = 'lazy';
                    media.appendChild(img);
                } else {
                    const placeholder = document.createElement('div');
                    placeholder.className = 'media-tile placeholder';
                    placeholder.textContent = tile.kind === 'video'
                        ? '▶ Video — open the post to watch'
                        : 'Image not downloaded';
                    media.appendChild(placeholder);
                }
            });
            card.appendChild(media);
        }

        if (post.post_url) {
            const footer = document.createElement('div');
            footer.className = 'post-footer';
            const link = document.createElement('a');
            link.href = post.post_url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = 'View on X ↗';
            footer.appendChild(link);
            card.appendChild(footer);
        }

        return card;
    }

    applyBtn.addEventListener('click', reload);
    folderInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') reload();
    });

    const observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadPage();
    });
    observer.observe(sentinel);

    restoreSettings();
})();
