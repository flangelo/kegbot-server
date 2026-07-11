/**
 * Real-time pour updates for fullscreen display via WebSocket.
 * Stacks all active pours in a panel (first-started on top).
 * Pauses the carousel while any pour is active.
 */

const FULLSCREEN_REALTIME_CONFIG = {
    wsUrl: (window.location.protocol === 'https:' ? 'wss://' : 'ws://') +
        window.location.host + '/ws/fullscreen/',
    settleTimeout: 500,    // ms of silence before a pour switches to "Poured"
    updateTimeout: 10000,  // ms of silence before a pour card is dropped
    mlToOz: 29.5735,
};

var currentPours = {};   // tapName → latest pourData
var pourOrder = [];      // tapNames in start order; index 0 = first-started = top of stack
var pourBaselines = {};  // tapName → volume_ml at pour start (cumulative meter offset)
var pourSettled = {};    // tapName → true once flow has stopped (shows "Poured")
var settleTimers = {};   // tapName → timeout id (Pouring → Poured)
var updateTimers = {};   // tapName → timeout id (card removal)
var wsConnection = null;

// ── WebSocket ──────────────────────────────────────────────────────────────

function connectWebSocket() {
    try {
        wsConnection = new WebSocket(FULLSCREEN_REALTIME_CONFIG.wsUrl);

        wsConnection.onopen = function() {
            console.log('WebSocket connected for fullscreen');
        };

        wsConnection.onmessage = function(event) {
            var data = JSON.parse(event.data);
            if (data.event_type === 'pour_update') {
                handlePourUpdate(data);
            } else if (data.event_type === 'pour_ended') {
                handlePourEnded(data);
            } else if (data.event_type === 'tap_state') {
                handleTapState(data);
            } else if (data.event_type === 'reload') {
                location.reload(true);
            }
        };

        wsConnection.onerror = function(error) {
            console.error('WebSocket error:', error);
        };

        wsConnection.onclose = function() {
            console.log('WebSocket closed, reconnecting in 3s…');
            setTimeout(connectWebSocket, 3000);
        };

    } catch (error) {
        console.error('Failed to connect WebSocket:', error);
        setTimeout(connectWebSocket, 3000);
    }
}

// ── Event handlers ─────────────────────────────────────────────────────────

function handlePourUpdate(pourData) {
    var tapName = pourData.tap;

    // New pour: record its position in the start order and the baseline volume
    if (pourOrder.indexOf(tapName) === -1) {
        pourOrder.push(tapName);
        pourBaselines[tapName] = pourData.volume_ml;
    }

    currentPours[tapName] = pourData;

    // An active flow event: this pour is "Pouring" again.
    pourSettled[tapName] = false;

    // After settleTimeout of silence, switch the card to "Poured".
    if (settleTimers[tapName]) {
        clearTimeout(settleTimers[tapName]);
    }
    settleTimers[tapName] = setTimeout(function() {
        pourSettled[tapName] = true;
        renderPourPanel();
    }, FULLSCREEN_REALTIME_CONFIG.settleTimeout);

    // After updateTimeout of silence, drop the card entirely.
    if (updateTimers[tapName]) {
        clearTimeout(updateTimers[tapName]);
    }
    updateTimers[tapName] = setTimeout(function() {
        removePour(tapName);
    }, FULLSCREEN_REALTIME_CONFIG.updateTimeout);

    renderPourPanel();
}

function handlePourEnded(pourData) {
    var tapName = pourData.tap;
    // Flow has explicitly stopped: switch to "Poured" now, but leave the card
    // up for the remainder of the idle timeout before removing it.
    if (settleTimers[tapName]) {
        clearTimeout(settleTimers[tapName]);
        delete settleTimers[tapName];
    }
    pourSettled[tapName] = true;
    renderPourPanel();
}

function removePour(tapName) {
    var idx = pourOrder.indexOf(tapName);
    if (idx !== -1) {
        pourOrder.splice(idx, 1);
    }
    if (settleTimers[tapName]) {
        clearTimeout(settleTimers[tapName]);
        delete settleTimers[tapName];
    }
    if (updateTimers[tapName]) {
        clearTimeout(updateTimers[tapName]);
        delete updateTimers[tapName];
    }
    delete currentPours[tapName];
    delete pourBaselines[tapName];
    delete pourSettled[tapName];
    renderPourPanel();
}

// ── Panel rendering ────────────────────────────────────────────────────────

function renderPourPanel() {
    var panel = document.getElementById('pour-panel');
    if (!panel) return;

    panel.innerHTML = '';

    if (pourOrder.length === 0) {
        panel.style.display = 'none';
        resumeCarousel();
        return;
    }

    pauseCarousel();
    panel.style.display = 'flex';

    pourOrder.forEach(function(tapName) {
        var pourData = currentPours[tapName];
        if (!pourData) return;

        var card = buildPourCard(pourData);
        panel.appendChild(card);
    });
}

function buildPourCard(pourData) {
    var baseline = pourBaselines[pourData.tap] || 0;
    var volumeOz = ((pourData.volume_ml - baseline) / FULLSCREEN_REALTIME_CONFIG.mlToOz).toFixed(1);

    var card = document.createElement('div');
    card.className = 'pour-card';

    if (pourData.beer_image_url) {
        var img = document.createElement('img');
        img.className = 'pour-card-image';
        img.src = pourData.beer_image_url;
        img.alt = pourData.beer_name || '';
        card.appendChild(img);
    }

    var info = document.createElement('div');
    info.className = 'pour-card-info';

    if (pourData.tap_name) {
        var tapEl = document.createElement('div');
        tapEl.className = 'pour-tap-name';
        tapEl.textContent = pourData.tap_name;
        info.appendChild(tapEl);
    }

    if (pourData.beer_name) {
        var beerEl = document.createElement('div');
        beerEl.className = 'pour-beer-name';
        beerEl.textContent = pourData.beer_name;
        info.appendChild(beerEl);
    }

    var titleEl = document.createElement('div');
    titleEl.className = 'pour-title';
    titleEl.textContent = pourSettled[pourData.tap] ? 'Poured' : 'Pouring…';
    info.appendChild(titleEl);

    var amountEl = document.createElement('div');
    amountEl.className = 'pour-amount';
    amountEl.textContent = volumeOz + ' oz';
    info.appendChild(amountEl);

    card.appendChild(info);
    return card;
}

// ── Carousel helpers ───────────────────────────────────────────────────────

function pauseCarousel() {
    if (window.slickCarousel && typeof window.slickCarousel.slick === 'function') {
        try { window.slickCarousel.slick('slickPause'); } catch (e) {}
    }
}

function resumeCarousel() {
    if (window.slickCarousel && typeof window.slickCarousel.slick === 'function') {
        try { window.slickCarousel.slick('slickPlay'); } catch (e) {}
    }
}

// ── Tap state updates ──────────────────────────────────────────────────────

function handleTapState(data) {
    var taps = data.taps || [];
    taps.forEach(function(tap) {
        var id = tap.tap_id;

        if (tap.volume_label) {
            var volEl = $('[data-tap-volume="' + id + '"]');
            if (volEl.length) {
                volEl.text(tap.volume_label + ' remaining');
            }
        }

        if (tap.temp_str) {
            var tempEl = $('[data-tap-temp="' + id + '"]');
            if (tempEl.length) {
                tempEl.text('Keg temperature: ' + tap.temp_str);
            }
        }

        if (tap.illustration_url) {
            $('[data-tap-illustration="' + id + '"]').attr('src', tap.illustration_url);
        }

        // low_status transitions in both directions (e.g. a fresh keg is
        // tapped), so update unconditionally rather than only when set.
        updateLowStatus(id, tap.low_status);
    });
}

function updateLowStatus(tapId, lowStatus) {
    var badgeEl = $('[data-tap-low="' + tapId + '"]');
    if (badgeEl.length) {
        badgeEl.removeClass('low critical');
        if (lowStatus === 'low' || lowStatus === 'critical') {
            badgeEl.addClass(lowStatus);
            badgeEl.text(lowStatus === 'critical' ? 'ALMOST EMPTY' : 'LOW KEG');
            badgeEl.removeAttr('hidden');
        } else {
            badgeEl.attr('hidden', 'hidden');
        }
    }

    var volEl = $('[data-tap-volume="' + tapId + '"]');
    if (volEl.length) {
        volEl.removeClass('label-info label-warning label-important');
        if (lowStatus === 'critical') {
            volEl.addClass('label-important');
        } else if (lowStatus === 'low') {
            volEl.addClass('label-warning');
        } else {
            volEl.addClass('label-info');
        }
    }
}

// ── Init ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
    setTimeout(connectWebSocket, 100);
});

window.addEventListener('beforeunload', function() {
    if (wsConnection) wsConnection.close();
});
