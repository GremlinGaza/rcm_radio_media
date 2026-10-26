// ========== HELPER: Create a program card ==========
function createProgramCard(program, large = false) {
    const statusClass = program.status;
    const statusLabels = {
        live: 'Facebook broadcast',
        format: 'Programming focus'
    };
    const statusLabel = statusLabels[program.status] || program.status;
    const facebookPageUrl = document.body.dataset.facebookPage;
    const actionUrl = program.url || facebookPageUrl;
    const actionLabel = program.action_label || 'Explore RCM Radio on Facebook';
    const time = program.time
        ? `<span><i class="fas fa-clock"></i> ${program.time}</span>`
        : '';
    const artwork = program.poster
        ? `<img class="program-poster" src="${program.poster}" alt="Poster for ${program.title}" loading="lazy" decoding="async">`
        : `<div class="program-art ${statusClass}" aria-hidden="true">
                <i class="fas ${program.icon || 'fa-radio'}"></i>
            </div>`;

    return `
        <div class="program-card ${large ? 'large' : ''}" data-status="${program.status}">
            ${artwork}
            <div class="card-body">
                <span class="badge ${statusClass}">${statusLabel}</span>
                <h3>${program.title}</h3>
                <p>${program.description}</p>
                <div class="meta">
                    <span><i class="fas fa-user"></i> ${program.host}</span>
                    ${time}
                    <span><i class="fas fa-tag"></i> ${program.category}</span>
                </div>
                <a class="program-channel-link" href="${actionUrl}" target="_blank" rel="noopener noreferrer">
                    <i class="fab fa-facebook"></i> ${actionLabel}
                </a>
            </div>
        </div>
    `;
}

// ========== LOAD LIVE PROGRAM ==========
async function loadLiveProgram(containerId) {
    try {
        const res = await fetch('/api/live');
        const program = await res.json();
        const container = document.getElementById(containerId);

        if (program) {
            container.innerHTML = createProgramCard(program, true);
        } else {
            container.innerHTML = '<p class="loading">No broadcast information is available right now.</p>';
        }
    } catch (err) {
        console.error(err);
        document.getElementById(containerId).innerHTML = '<p class="loading">Could not load live show.</p>';
    }
}

// ========== LOAD UPCOMING ==========
async function loadUpcoming() {
    try {
        const res = await fetch('/api/upcoming');
        if (!res.ok) {
            throw new Error(`Could not load the schedule (${res.status}).`);
        }
        const programs = await res.json();
        const container = document.getElementById('upcoming-list');

        if (programs.length === 0) {
            container.innerHTML = '<p class="loading">No upcoming shows scheduled.</p>';
            return;
        }

        container.innerHTML = programs.map(p => createProgramCard(p)).join('');
    } catch (err) {
        console.error(err);
    }
}

// ========== LOAD ALL PROGRAMS ==========
let allPrograms = [];
let activeProgramFilter = 'all';

async function loadAllPrograms() {
    try {
        const res = await fetch('/api/programs');
        if (!res.ok) {
            throw new Error(`Could not load RCM Radio programming (${res.status}).`);
        }
        allPrograms = await res.json();
        filterAndRenderPrograms();
    } catch (err) {
        console.error(err);
        const container = document.getElementById('all-programs');
        if (container) {
            container.innerHTML = '<p class="loading">Could not load programming. Please try again later.</p>';
        }
    }
}

function renderPrograms(programs) {
    const container = document.getElementById('all-programs');
    if (!container) {
        return;
    }
    const results = document.getElementById('program-results');
    if (results) {
        results.textContent = `${programs.length} ${programs.length === 1 ? 'result' : 'results'}`;
    }
    if (programs.length === 0) {
        container.innerHTML = '<p class="loading">No programming matches. Try another filter or search.</p>';
        return;
    }
    container.innerHTML = programs.map(p => createProgramCard(p)).join('');
}

function filterAndRenderPrograms() {
    const searchInput = document.getElementById('program-search');
    const query = searchInput ? searchInput.value.trim().toLocaleLowerCase() : '';
    const filtered = allPrograms.filter(program => {
        const matchesFilter = activeProgramFilter === 'all'
            || program.category_id.startsWith(`${activeProgramFilter}-`);
        const searchableText = `${program.title} ${program.host} ${program.time} ${program.description} ${program.category}`
            .toLocaleLowerCase();
        return matchesFilter && searchableText.includes(query);
    });
    renderPrograms(filtered);
}

// ========== FILTERS ==========
function setupFilters() {
    const buttons = document.querySelectorAll('.filter-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            buttons.forEach(button => button.setAttribute('aria-pressed', String(button === btn)));
            activeProgramFilter = btn.dataset.filter || 'all';
            filterAndRenderPrograms();
        });
    });
}

function setupProgramSearch() {
    const searchInput = document.getElementById('program-search');
    if (searchInput) {
        searchInput.addEventListener('input', filterAndRenderPrograms);
    }
}

async function loadProgramFocus() {
    const container = document.getElementById('program-focus');
    if (!container) {
        return;
    }
    try {
        const response = await fetch('/api/programs');
        if (!response.ok) {
            throw new Error(`Could not load programming (${response.status}).`);
        }
        const programs = await response.json();
        const formats = programs.filter(program => program.status !== 'live');
        container.innerHTML = formats.length
            ? formats.map(program => createProgramCard(program)).join('')
            : '<p class="loading">No programming information is available.</p>';
    } catch (error) {
        console.error(error);
        container.innerHTML = '<p class="loading">Could not load programming information.</p>';
    }
}

// ========== LOAD YOUTUBE CHANNEL VIDEOS ==========
function initializeChannelPlayer(videos) {
    const frame = document.getElementById('channel-player-frame');
    const queue = document.getElementById('channel-video-queue');
    if (!frame || !queue) {
        return;
    }

    const channelId = document.body.dataset.youtubeChannelId;
    const validVideos = videos.filter(video => /^[A-Za-z0-9_-]{11}$/.test(video.id));
    const sequence = validVideos;
    const title = document.getElementById('player-video-title');
    const details = document.getElementById('player-video-details');
    const status = document.getElementById('player-status');
    const badge = document.getElementById('player-live-badge');
    const controls = document.getElementById('playlist-controls');
    const buttons = document.querySelectorAll('[data-player-mode]');
    let currentIndex = -1;

    const setLiveMode = () => {
        frame.src = `https://www.youtube.com/embed/live_stream?channel=${encodeURIComponent(channelId)}`;
        frame.title = 'RCM Radio Media live YouTube broadcast';
        title.textContent = 'RCM Radio Media live broadcast';
        details.textContent = 'The YouTube player includes its own video and audio controls.';
        status.textContent = 'If the channel is not currently broadcasting, choose a video from the sequence.';
        badge.hidden = false;
        controls.hidden = true;
        currentIndex = -1;
        buttons.forEach(button => {
            const isLive = button.dataset.playerMode === 'live';
            button.classList.toggle('active', isLive);
            button.setAttribute('aria-pressed', String(isLive));
        });
        renderChannelQueue();
    };

    const playVideo = (index, autoplay = true) => {
        if (sequence.length === 0) {
            status.textContent = 'No videos are currently available from this channel.';
            return;
        }
        currentIndex = (index + sequence.length) % sequence.length;
        const video = sequence[currentIndex];
        frame.src = `https://www.youtube-nocookie.com/embed/${video.id}${autoplay ? '?autoplay=1' : ''}`;
        frame.title = video.title;
        title.textContent = video.title;
        const dateLabel = video.published_at
            ? new Date(video.published_at).toLocaleDateString()
            : 'Date unavailable';
        details.textContent = `${video.series || video.program || 'RCM Media'} · Published ${dateLabel}`;
        status.textContent = `Video ${currentIndex + 1} of ${sequence.length} in the channel sequence.`;
        badge.hidden = true;
        controls.hidden = false;
        buttons.forEach(button => {
            const isVideos = button.dataset.playerMode === 'videos';
            button.classList.toggle('active', isVideos);
            button.setAttribute('aria-pressed', String(isVideos));
        });
        renderChannelQueue();
    };

    function renderChannelQueue() {
        queue.replaceChildren();
        if (sequence.length === 0) {
            const empty = document.createElement('li');
            empty.textContent = 'No recent channel videos found.';
            queue.appendChild(empty);
            return;
        }

        sequence.forEach((video, index) => {
            const item = document.createElement('li');
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'queue-video';
            if (index === currentIndex) {
                button.classList.add('selected');
                button.setAttribute('aria-current', 'true');
            }

            const videoTitle = document.createElement('span');
            videoTitle.textContent = video.title;
            const videoSeries = document.createElement('small');
            videoSeries.textContent = video.series || video.program || 'RCM Media';
            button.append(videoTitle, videoSeries);
            button.addEventListener('click', () => playVideo(index));
            item.appendChild(button);
            queue.appendChild(item);
        });
    }

    buttons.forEach(button => {
        button.addEventListener('click', () => {
            if (button.dataset.playerMode === 'live') {
                setLiveMode();
            } else if (sequence.length > 0) {
                playVideo(currentIndex < 0 ? 0 : currentIndex);
            } else {
                status.textContent = 'No videos are currently available from this channel.';
            }
        });
    });

    document.querySelectorAll('[data-video-step]').forEach(button => {
        button.addEventListener('click', () => {
            playVideo(currentIndex + Number(button.dataset.videoStep));
        });
    });

    setLiveMode();
}

async function loadYouTubeVideos() {
    const containers = document.querySelectorAll('[data-youtube-videos]');
    const hasPlayer = document.getElementById('channel-player-frame') !== null;
    if (containers.length === 0 && !hasPlayer) {
        return;
    }

    try {
        const response = await fetch('/api/youtube-videos');
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'Could not load RCM Media videos.');
        }

        initializeChannelPlayer(result);
        containers.forEach(container => {
            if (result.length === 0) {
                container.textContent = 'No recent videos are available.';
                return;
            }

            container.replaceChildren();
            result.forEach(video => {
                if (!/^[A-Za-z0-9_-]{11}$/.test(video.id)) {
                    return;
                }

                const card = document.createElement('article');
                card.className = 'video-card';

                const frame = document.createElement('iframe');
                frame.src = `https://www.youtube-nocookie.com/embed/${video.id}`;
                frame.title = video.title;
                frame.loading = 'lazy';
                frame.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
                frame.referrerPolicy = 'strict-origin-when-cross-origin';
                frame.allowFullscreen = true;
                card.appendChild(frame);

                const title = document.createElement('h3');
                title.textContent = video.title;
                card.appendChild(title);

                if (video.published_at) {
                    const published = document.createElement('p');
                    published.className = 'video-date';
                    const parsedDate = new Date(video.published_at);
                    published.textContent = Number.isNaN(parsedDate.getTime())
                        ? `Published ${video.published_at}`
                        : `Published ${parsedDate.toLocaleDateString()}`;
                    card.appendChild(published);
                }

                if (video.program) {
                    const program = document.createElement('p');
                    program.className = 'video-program';
                    program.textContent = `Related show: ${video.program}`;
                    card.appendChild(program);
                }

                container.appendChild(card);
            });
        });
    } catch (error) {
        console.error(error);
        const playerStatus = document.getElementById('player-status');
        if (playerStatus) {
            playerStatus.textContent = 'Could not load the program video sequence. The live player remains available.';
        }
        containers.forEach(container => {
            container.textContent = 'RCM Media videos could not be loaded right now. Please try again later.';
        });
    }
}

document.addEventListener('DOMContentLoaded', loadYouTubeVideos);