const API_ROOT = 'https://api.github.com/repos/Amne-Dev/waguri-read/contents/panels';
const PANEL_EXTENSIONS = ['.webp', '.png'];
const mobileQuery = window.matchMedia('(max-width: 640px)');

const state = {
	chapters: [],
	panelCounts: new Map(),
	currentChapter: null,
	loadingChapter: false,
};

const elements = {
	chapterList: document.getElementById('chapterList'),
	chapterStatus: document.getElementById('chapterStatus'),
	panelStatus: document.getElementById('panelStatus'),
	panelStack: document.getElementById('panelStack'),
	chapterTitle: document.getElementById('chapterTitle'),
	panelCount: document.getElementById('panelCount'),
	refreshChapters: document.getElementById('refreshChapters'),
	scrollTop: document.getElementById('scrollTop'),
	panelColumn: document.querySelector('.panel-column'),
	focusToggle: document.getElementById('focusToggle'),
	chapterToggle: document.getElementById('chapterToggle'),
	chapterColumn: document.querySelector('.chapter-column'),
	chapterHeader: document.querySelector('.chapter-header'),
	chapterCurrentLabel: document.getElementById('chapterCurrentLabel'),
	prevChapterTop: document.getElementById('prevChapterTop'),
	nextChapterTop: document.getElementById('nextChapterTop'),
	prevChapterBottom: document.getElementById('prevChapterBottom'),
	nextChapterBottom: document.getElementById('nextChapterBottom'),
};

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

init();

function init() {
	elements.chapterList?.addEventListener('click', handleChapterClick);
	elements.refreshChapters?.addEventListener('click', () => loadChapters(true));
	elements.scrollTop?.addEventListener('click', () => {
		elements.panelColumn?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		window.scrollBy({ top: -24, behavior: 'smooth' });
	});
	elements.focusToggle?.addEventListener('click', toggleFocusMode);
	elements.chapterToggle?.addEventListener('click', () => setChapterCollapsed(!isChapterCollapsed()));
	elements.chapterHeader?.addEventListener('click', (event) => {
		if (!isMobileView()) return;
		if (event.target.closest('button')) return;
		setChapterCollapsed(!isChapterCollapsed());
	});
	elements.prevChapterTop?.addEventListener('click', () => changeChapter(-1));
	elements.prevChapterBottom?.addEventListener('click', () => changeChapter(-1));
	elements.nextChapterTop?.addEventListener('click', () => changeChapter(1));
	elements.nextChapterBottom?.addEventListener('click', () => changeChapter(1));

	if (mobileQuery) {
		if (mobileQuery.addEventListener) {
			mobileQuery.addEventListener('change', handleViewportChange);
		} else if (mobileQuery.addListener) {
			mobileQuery.addListener(handleViewportChange);
		}
	}

	loadChapters();
	setChapterCollapsed(false);
	updateFocusButton();
	updateCurrentChapterLabel();
	updateChapterNavButtons();
}

async function loadChapters(isManual = false) {
	toggleChapterStatus('Loading chapter list…');
	setButtonLoading(elements.refreshChapters, true);

	try {
		const payload = await fetchJSON(API_ROOT);
		const dirs = payload.filter((entry) => entry.type === 'dir');
		state.chapters = dirs
			.sort((a, b) => collator.compare(formatChapterLabel(a.name), formatChapterLabel(b.name)))
			.map((dir) => ({
			name: dir.name,
			url: dir.url,
			}));

		renderChapters();
		updateChapterNavButtons();
		updateCurrentChapterLabel(state.currentChapter);

		if (!state.currentChapter && state.chapters.length) {
			loadChapterPanels(state.chapters[0]);
		} else if (isManual && state.currentChapter) {
			const match = state.chapters.find((entry) => entry.name === state.currentChapter);
			if (match) {
				loadChapterPanels(match);
			}
		}
	} catch (error) {
		console.error(error);
		toggleChapterStatus(formatError(error));
	} finally {
		setButtonLoading(elements.refreshChapters, false);
	}
}

async function loadChapterPanels(chapter) {
	if (!chapter || state.loadingChapter) return;
	state.loadingChapter = true;
	state.currentChapter = chapter.name;
	highlightActiveChapter();

	togglePanelStatus('Loading panels…');
				updateCurrentChapterLabel(chapter.name);
				updateChapterNavButtons();
	elements.panelStack.innerHTML = '';
	elements.chapterTitle.textContent = formatChapterLabel(chapter.name);
	elements.panelCount.textContent = '0 panels';

	try {
		const payload = await fetchJSON(`${API_ROOT}/${encodeURIComponent(chapter.name)}`);
		const panels = payload
			.filter((entry) => entry.type === 'file' && PANEL_EXTENSIONS.some((ext) => entry.name.toLowerCase().endsWith(ext)))
			.sort((a, b) => collator.compare(a.name, b.name))
			.map((file, index) => ({
				order: index + 1,
				name: file.name,
				url: file.download_url,
			}));

		if (!panels.length) {
			togglePanelStatus('No panels found in this chapter yet.');
			return;
		}

		state.panelCounts.set(chapter.name, panels.length);
		renderPanels(panels);
		elements.panelCount.textContent = `${panels.length} panel${panels.length === 1 ? '' : 's'}`;
		if (isMobileView()) {
			setChapterCollapsed(true);
		}
		togglePanelStatus('');
	} catch (error) {
		console.error(error);
		togglePanelStatus(formatError(error));
	} finally {
		state.loadingChapter = false;
		highlightActiveChapter();
	}
}

function renderChapters() {
	if (!elements.chapterList) return;
	elements.chapterList.innerHTML = '';

	if (!state.chapters.length) {
		toggleChapterStatus('No chapters found inside panels/.');
		return;
	}

	toggleChapterStatus('');

	state.chapters.forEach((chapter) => {
		const button = document.createElement('button');
		button.type = 'button';
		button.className = 'chapter-pill';
		button.dataset.chapter = chapter.name;
		const label = formatChapterLabel(chapter.name);

		const count = state.panelCounts.get(chapter.name);
		button.innerHTML = `
			<strong>${label}</strong>
			<span>${count ? `${count} panel${count === 1 ? '' : 's'}` : 'tap to load'}</span>
		`;

		if (chapter.name === state.currentChapter) {
			button.classList.add('active');
		}

		elements.chapterList.appendChild(button);
	});
}

function renderPanels(panels) {
	if (!elements.panelStack) return;
	elements.panelStack.innerHTML = '';
	const chapterLabel = formatChapterLabel(state.currentChapter);

	panels.forEach((panel) => {
		const img = document.createElement('img');
		img.loading = 'lazy';
		img.decoding = 'async';
		img.alt = `${chapterLabel} panel ${panel.order}`;
		img.className = 'panel-image';
		img.src = `${panel.url}?cacheBust=${Date.now()}`;

		img.onerror = () => {
			img.alt = 'Panel failed to load';
		};

		elements.panelStack.appendChild(img);
	});
}

function handleChapterClick(event) {
	const pill = event.target.closest('.chapter-pill');
	if (!pill) return;
	const { chapter } = pill.dataset;
	if (!chapter) return;

	const match = state.chapters.find((entry) => entry.name === chapter);
	if (match) {
		loadChapterPanels(match);
	}
}

function highlightActiveChapter() {
	if (!elements.chapterList) return;
	[...elements.chapterList.children].forEach((child) => {
		child.classList.toggle('active', child.dataset.chapter === state.currentChapter);
	});
}

function changeChapter(delta) {
	if (state.loadingChapter) return;
	if (!state.chapters.length) return;
	const currentIndex = state.chapters.findIndex((entry) => entry.name === state.currentChapter);
	if (currentIndex === -1) return;
	const next = state.chapters[currentIndex + delta];
	if (next) {
		loadChapterPanels(next);
	}
}

async function fetchJSON(url) {
	const response = await fetch(url, {
		headers: {
			'Accept': 'application/vnd.github+json',
		},
	});
	if (!response.ok) {
		const message = response.status === 403
			? 'GitHub API rate limit hit. Try again in a minute.'
			: `GitHub API error (${response.status}).`;
		throw new Error(message);
	}
	return response.json();
}

function toggleChapterStatus(message) {
	updateStatusBlock(elements.chapterStatus, message);
}

function togglePanelStatus(message) {
	updateStatusBlock(elements.panelStatus, message);
}

function updateStatusBlock(node, message) {
	if (!node) return;
	if (!message) {
		node.textContent = '';
		node.style.display = 'none';
	} else {
		node.textContent = message;
		node.style.display = '';
	}
}

function setButtonLoading(button, isLoading) {
	if (!button) return;
	if (!button.dataset.label) {
		button.dataset.label = button.textContent.trim();
	}
	button.disabled = isLoading;
	button.textContent = isLoading ? 'Loading…' : button.dataset.label;
}

function formatError(error) {
	return error instanceof Error ? error.message : 'Something went wrong.';
}

function formatChapterLabel(rawName) {
	if (!rawName) return '';
	const noUnderscore = rawName.replace(/_/g, ' ');
	const withoutVolume = noUnderscore.replace(/volume\s*\d+/gi, '');
	const cleaned = withoutVolume.replace(/\s+/g, ' ').trim();
	if (!cleaned) return rawName;
	return cleaned.replace(/\b([a-z])/gi, (match) => match.toUpperCase());
}

function updateCurrentChapterLabel(rawName) {
	if (!elements.chapterCurrentLabel) return;
	if (!rawName) {
		elements.chapterCurrentLabel.textContent = 'No chapter selected';
		return;
	}
	elements.chapterCurrentLabel.textContent = `Viewing: ${formatChapterLabel(rawName)}`;
}

function updateChapterNavButtons() {
	const index = state.chapters.findIndex((entry) => entry.name === state.currentChapter);
	const atStart = index <= 0;
	const atEnd = index === -1 || index >= state.chapters.length - 1;
	setNavDisabled(elements.prevChapterTop, atStart);
	setNavDisabled(elements.prevChapterBottom, atStart);
	setNavDisabled(elements.nextChapterTop, atEnd);
	setNavDisabled(elements.nextChapterBottom, atEnd);
}

function setNavDisabled(button, disabled) {
	if (!button) return;
	button.disabled = disabled;
}

function toggleFocusMode() {
	document.body.classList.toggle('focus-only');
	updateFocusButton();
}

function updateFocusButton() {
	if (!elements.focusToggle) return;
	const active = document.body.classList.contains('focus-only');
	elements.focusToggle.textContent = active ? 'Exit focus' : 'Focus mode';
}

function setChapterCollapsed(collapsed) {
	if (!elements.chapterColumn) return;
	elements.chapterColumn.classList.toggle('collapsed', collapsed);
	elements.chapterColumn.setAttribute('aria-expanded', (!collapsed).toString());
	if (elements.chapterToggle) {
		elements.chapterToggle.textContent = collapsed ? 'Show chapters' : 'Hide chapters';
	}
}

function isChapterCollapsed() {
	return elements.chapterColumn?.classList.contains('collapsed') ?? false;
}

function isMobileView() {
	return mobileQuery?.matches ?? false;
}

function handleViewportChange(event) {
	const matches = typeof event.matches === 'boolean' ? event.matches : mobileQuery?.matches;
	if (!matches) {
		setChapterCollapsed(false);
	}
}
