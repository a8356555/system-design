## 1. how celery background task triggered? like cronjob or?

1. API Triggered (90% of tasks): User interactions immediately trigger background processing
2. Cron Scheduled (Celery Beat): Regular maintenance, analytics, model updates e.g. hourly_trending_analysis() or ml_model_retrain()
3. Event Driven: Message queue events trigger related tasks
4. Chained/Grouped: Complex workflows with dependencies

## 2. why use background task?

to prevent synchronous blocking processing -> user_interaction tracking should not block video playing

click play -> async track user_interaction and calculate in the background -> start playing imediately

## 3. fast api background_task vs celery

fast api run in same process -> good for simple, fast operations and operations that is ok to failed

celery run in different process, good for heavy operations e.g. ml processing and operations that must complete e.g. payment

## 4. in websocket, when will websocket.receive_text()? when will client send text to websocket? what scenario will frontend requestFreshRecommendations be called

1. Page Focus/Visibility Changes
    ```javascript
    // User switches back to Netflix tab after being away
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            console.log('User returned to Netflix tab');
            // Request fresh recommendations in case something changed
            recWebSocket.requestFreshRecommendations();
        }
    });

    // User switches between browser tabs
    window.addEventListener('focus', () => {
        console.log('Netflix tab gained focus');
        recWebSocket.requestFreshRecommendations();
    });

2. Device/Screen Changes

3. User Interface Actions

    ```javascript
    // User manually refreshes homepage
    function refreshHomepage() {
        showLoadingSpinner();
        recWebSocket.requestFreshRecommendations();
    }

    // User scrolls to bottom of recommendations
    function handleScroll() {
        if (isNearBottomOfPage()) {
            console.log('User scrolled to bottom - loading more recommendations');
            recWebSocket.ws.send(JSON.stringify({
                type: "request_more_recommendations",
                current_count: getCurrentRecommendationCount(),
                category: getCurrentCategory()
            }));
        }
    }

    // User changes profile
    function switchProfile(newProfileId) {
        // Close current WebSocket
        recWebSocket.disconnect();

        // Create new WebSocket for different profile
        recWebSocket = new RecommendationWebSocket(userId, newProfileId);
        recWebSocket.connect();
    }

4. Time-Based Triggers
    ```javascript
    // Periodic refresh for active users
    setInterval(() => {
        if (isUserActive() && document.visibilityState === 'visible') {
            console.log('Periodic refresh for active user');
            recWebSocket.requestFreshRecommendations();
        }
    }, 5 * 60 * 1000); // Every 5 minutes

    // Time-of-day context changes
    function checkTimeBasedContext() {
        const currentHour = new Date().getHours();
        const lastContextHour = localStorage.getItem('lastContextHour');

        // If hour changed significantly (morning -> afternoon -> evening)
        if (Math.abs(currentHour - lastContextHour) >= 3) {
            console.log('Time context changed significantly');
            recWebSocket.sendContextUpdate({
                time_context_change: true,
                previous_hour: lastContextHour,
                current_hour: currentHour
            });
            localStorage.setItem('lastContextHour', currentHour);
        }
    }


## 5. websocket vs server sent events

  | Feature             | WebSocket             | Server-Sent Events          |
  |---------------------|-----------------------|-----------------------------|
  | Communication       | ⬅️➡️ Bidirectional    | ➡️ Server → Client only     |
  | Protocol            | Custom WS protocol    | Standard HTTP/1.1 or HTTP/2 |
  | Complexity          | Higher                | Lower                       |
  | Browser Support     | Excellent             | Excellent                   |
  | Firewall/Proxy      | Sometimes blocked     | HTTP - always works         |
  | Auto Reconnection   | Manual implementation | Built-in automatic          |
  | Connection Overhead | Lower                 | Higher (HTTP headers)       |
  | Message Format      | Any format            | Text-based                  |

 
   | Use Case                       | Recommended Technology | Reason                  |
  |--------------------------------|------------------------|-------------------------|
  | Autoplay countdown with cancel | WebSocket              | Need bidirectional      |
  | Trending content updates       | SSE                    | One-way push only       |
  | User requesting specific recs  | WebSocket              | Request-response needed |
  | Background homepage refresh    | SSE                    | Simple push updates     |
  | Interactive content choices    | WebSocket              | Complex interactions    |
  | System status notifications    | SSE                    | Simple broadcasting     |
  | Real-time collaboration        | WebSocket              | Bidirectional required  |
  | Analytics dashboard updates    | SSE                    | Display-only updates    |Choose WebSocket When:

  ✅ Need bidirectional communication
  - User can cancel autoplay
  - User requests specific recommendations
  - Real-time interactions (chat, collaboration)
  - Gaming-like features

  ✅ Low latency critical
  - Immediate autoplay countdown
  - Real-time video sync
  - Live reactions/comments

  ✅ Complex message patterns
  - Request-response cycles
  - User commands
  - State synchronization


Choose SSE When:

  ✅ Only need server → client updates
  - Trending content updates
  - New releases notifications
  - Background cache updates
  - Analytics dashboards

  ✅ Simpler implementation preferred
  - Just push notifications
  - Status updates
  - Monitoring data

  ✅ Network/firewall concerns
  - Corporate environments
  - Strict proxy settings
  - Standard HTTP required



## 6. in Complete Event Processing Pipeline, when track_interaction will be called
```javascript
    // Netflix-like video player integration
    class NetflixVideoPlayer {
        constructor(videoElement, contentId, userId, profileId) {
            this.video = videoElement;
            this.contentId = contentId;
            this.userId = userId;
            this.profileId = profileId;

            this.setupEventListeners();
        }

        setupEventListeners() {
            // 1️⃣ WHEN: User clicks play button
            this.video.addEventListener('play', () => {
                console.log('📹 Video started playing');
                this.trackInteraction('play', {
                    timestamp: new Date().toISOString(),
                    progress_seconds: 0
                });
            });

            // 2️⃣ WHEN: User pauses video
            this.video.addEventListener('pause', () => {
                console.log('⏸️ Video paused');
                this.trackInteraction('pause', {
                    progress_seconds: Math.floor(this.video.currentTime),
                    duration_watched_seconds: this.getDurationWatched()
                });
            });

            // 3️⃣ WHEN: Video ends naturally
            this.video.addEventListener('ended', () => {
                console.log('🏁 Video completed');
                this.trackInteraction('complete', {
                    progress_seconds: Math.floor(this.video.duration),
                    completion_percentage: 100,
                    total_watch_time: this.getTotalWatchTime()
                });
            });

            // 4️⃣ WHEN: User seeks/scrubs through video
            this.video.addEventListener('seeked', () => {
                console.log('⏭️ User seeked to position');
                this.trackInteraction('seek', {
                    progress_seconds: Math.floor(this.video.currentTime),
                    seek_from: this.previousPosition,
                    seek_to: this.video.currentTime
                });
            });

            // 5️⃣ WHEN: Progress tracking (every 30 seconds)
            setInterval(() => {
                if (!this.video.paused && !this.video.ended) {
                    console.log('⏰ Progress update');
                    this.trackInteraction('progress_update', {
                        progress_seconds: Math.floor(this.video.currentTime),
                        buffer_health: this.getBufferHealth(),
                        playback_quality: this.getPlaybackQuality()
                    });
                }
            }, 30000); // Every 30 seconds
        }

        // 🎯 THIS IS THE ACTUAL API CALL
        trackInteraction(interactionType, additionalData = {}) {
            fetch('/recommendations/interaction', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    user_id: this.userId,
                    profile_id: this.profileId,
                    content_id: this.contentId,
                    interaction_type: interactionType,
                    session_id: this.getSessionId(),
                    device_type: this.getDeviceType(),
                    timestamp: new Date().toISOString(),
                    ...additionalData
                })
            });
        }
    }
```


## 7. in update_trending_analysis, why we need to increment interaction counters using redis
* TRENDING: Recent interaction velocity
```python
  def process_user_interaction(interaction_data):
      # This runs for EVERY interaction
      update_trending_analysis(
          interaction_data["content_id"],
          interaction_data["interaction_type"]
      )

  def update_trending_analysis(content_id, interaction_type):
      # Wednesday episode counter goes from 45,231 to 45,232
      redis_client.zincrby("trending:hourly", 1, "wednesday_s1e1")

      # When thousands of users do this simultaneously:
      # wednesday_s1e1 counter: 45,232 → 46,847 → 48,293 → 51,445
      # Algorithm detects rapid growth = TRENDING! 🔥

  content_recent_interactions = {
      "wednesday_s1e1": 500_000,       # 🔥 HOT - high recent activity
      "stranger_things_s1e1": 50_000, # Stable but not trending
      "friends_s1e1": 20_000          # Low recent activity
  }
```

🎯 Why Not Just Database Queries?

  Performance Comparison:

  ❌ SLOW: Database query for trending (100ms - 2 seconds)

  # ✅ FAST: Redis sorted set lookup (1-5ms)  

## 8. where is EventProducer, RecommendationEventConsumer used in production ready arch
* see documentation
