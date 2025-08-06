package main

import (
    "bytes"
    "context"
    "crypto/tls"
    "encoding/base64"
    "fmt"
    "html/template"
    "log"
    "mime"
    "mime/multipart"
    "net/smtp"
    "path/filepath"
    "strings"
    "sync"
    "time"
)

// SMTPClient handles email delivery via SMTP
type SMTPClient struct {
    config      *SMTPConfig
    auth        smtp.Auth
    rateLimiter *EmailRateLimiter
    templates   map[string]*template.Template
    metrics     *EmailMetrics
    mu          sync.RWMutex
    healthy     bool
}

// SMTPConfig contains SMTP server configuration
type SMTPConfig struct {
    Host                string `json:"host"`
    Port                int    `json:"port"`
    Username            string `json:"username"`
    Password            string `json:"password"`
    From                string `json:"from"`
    FromName            string `json:"from_name"`
    UseTLS              bool   `json:"use_tls"`
    InsecureSkipVerify  bool   `json:"insecure_skip_verify"`
    MaxConnections      int    `json:"max_connections"`
    ConnectionTimeout   int    `json:"connection_timeout"`
    SendTimeout         int    `json:"send_timeout"`
    RateLimitPerMinute  int    `json:"rate_limit_per_minute"`
    MaxRetries          int    `json:"max_retries"`
    BatchSize           int    `json:"batch_size"`
}

// EmailMessage represents an email message
type EmailMessage struct {
    To          []string          `json:"to"`
    CC          []string          `json:"cc,omitempty"`
    BCC         []string          `json:"bcc,omitempty"`
    Subject     string            `json:"subject"`
    Body        string            `json:"body"`
    HTMLBody    string            `json:"html_body,omitempty"`
    Attachments []EmailAttachment `json:"attachments,omitempty"`
    Headers     map[string]string `json:"headers,omitempty"`
    Priority    string            `json:"priority"` // low, normal, high
    Template    string            `json:"template,omitempty"`
    TemplateData map[string]interface{} `json:"template_data,omitempty"`
}

// EmailAttachment represents an email attachment
type EmailAttachment struct {
    Filename    string `json:"filename"`
    ContentType string `json:"content_type"`
    Data        []byte `json:"data"`
    Inline      bool   `json:"inline"`
}

// EmailResponse represents the response from email sending
type EmailResponse struct {
    MessageID string `json:"message_id"`
    Success   bool   `json:"success"`
    Error     string `json:"error,omitempty"`
    Timestamp time.Time `json:"timestamp"`
}

// EmailMetrics tracks email sending metrics
type EmailMetrics struct {
    EmailsSent     int64     `json:"emails_sent"`
    EmailsDelivered int64     `json:"emails_delivered"`
    EmailsFailed   int64     `json:"emails_failed"`
    BounceRate     float64   `json:"bounce_rate"`
    LastHealthCheck time.Time `json:"last_health_check"`
    mu             sync.RWMutex
}

// EmailRateLimiter implements rate limiting for email sending
type EmailRateLimiter struct {
    maxPerMinute int
    sent         []time.Time
    mu           sync.Mutex
}

// NewSMTPClient creates a new SMTP email client
func NewSMTPClient(config *SMTPConfig) (*SMTPClient, error) {
    // Setup authentication
    auth := smtp.PlainAuth("", config.Username, config.Password, config.Host)

    // Initialize rate limiter
    rateLimiter := &EmailRateLimiter{
        maxPerMinute: config.RateLimitPerMinute,
        sent:         make([]time.Time, 0),
    }

    client := &SMTPClient{
        config:      config,
        auth:        auth,
        rateLimiter: rateLimiter,
        templates:   make(map[string]*template.Template),
        metrics:     &EmailMetrics{},
        healthy:     true,
    }

    // Load email templates
    if err := client.loadTemplates(); err != nil {
        log.Printf("Warning: Failed to load email templates: %v", err)
    }

    // Start health check routine
    go client.healthCheckRoutine()

    log.Printf("SMTP client initialized for %s:%d", config.Host, config.Port)
    return client, nil
}

// SendEmail sends a single email
func (s *SMTPClient) SendEmail(ctx context.Context, email *EmailMessage) (*EmailResponse, error) {
    // Check rate limiting
    if !s.rateLimiter.Allow() {
        return &EmailResponse{
            Success:   false,
            Error:     "Rate limit exceeded",
            Timestamp: time.Now(),
        }, fmt.Errorf("rate limit exceeded")
    }

    // Render template if specified
    if email.Template != "" {
        if err := s.renderTemplate(email); err != nil {
            return &EmailResponse{
                Success:   false,
                Error:     fmt.Sprintf("Template rendering failed: %v", err),
                Timestamp: time.Now(),
            }, err
        }
    }

    // Validate email
    if err := s.validateEmail(email); err != nil {
        return &EmailResponse{
            Success:   false,
            Error:     fmt.Sprintf("Email validation failed: %v", err),
            Timestamp: time.Now(),
        }, err
    }

    // Build email message
    message, err := s.buildMessage(email)
    if err != nil {
        return &EmailResponse{
            Success:   false,
            Error:     fmt.Sprintf("Message building failed: %v", err),
            Timestamp: time.Now(),
        }, fmt.Errorf("failed to build message: %w", err)
    }

    // Send with retries
    var response *EmailResponse
    for attempt := 0; attempt <= s.config.MaxRetries; attempt++ {
        response, err = s.sendWithRetry(ctx, email, message, attempt)
        if err == nil && response.Success {
            break
        }

        if attempt < s.config.MaxRetries {
            backoffDelay := time.Duration(attempt*attempt) * time.Second
            time.Sleep(backoffDelay)
            log.Printf("Email send attempt %d failed, retrying in %v", attempt+1, backoffDelay)
        }
    }

    // Update metrics
    s.updateMetrics(response, err)

    return response, err
}

// sendWithRetry attempts to send email with retry logic
func (s *SMTPClient) sendWithRetry(ctx context.Context, email *EmailMessage, message []byte, attempt int) (*EmailResponse, error) {
    // Create connection with timeout
    connCtx, cancel := context.WithTimeout(ctx, time.Duration(s.config.ConnectionTimeout)*time.Second)
    defer cancel()

    // Connect to SMTP server
    conn, err := s.connectSMTP(connCtx)
    if err != nil {
        return &EmailResponse{
            Success:   false,
            Error:     fmt.Sprintf("SMTP connection failed: %v", err),
            Timestamp: time.Now(),
        }, err
    }
    defer conn.Quit()

    // Set sender
    if err := conn.Mail(s.config.From); err != nil {
        return &EmailResponse{
            Success:   false,
            Error:     fmt.Sprintf("MAIL command failed: %v", err),
            Timestamp: time.Now(),
        }, err
    }

    // Set recipients
    allRecipients := append(append(email.To, email.CC...), email.BCC...)
    for _, recipient := range allRecipients {
        if err := conn.Rcpt(strings.TrimSpace(recipient)); err != nil {
            log.Printf("RCPT command failed for %s: %v", recipient, err)
            // Continue with other recipients
        }
    }

    // Send email data
    writer, err := conn.Data()
    if err != nil {
        return &EmailResponse{
            Success:   false,
            Error:     fmt.Sprintf("DATA command failed: %v", err),
            Timestamp: time.Now(),
        }, err
    }

    _, err = writer.Write(message)
    if err != nil {
        writer.Close()
        return &EmailResponse{
            Success:   false,
            Error:     fmt.Sprintf("Message write failed: %v", err),
            Timestamp: time.Now(),
        }, err
    }

    err = writer.Close()
    if err != nil {
        return &EmailResponse{
            Success:   false,
            Error:     fmt.Sprintf("Message close failed: %v", err),
            Timestamp: time.Now(),
        }, err
    }

    messageID := s.generateMessageID()
    return &EmailResponse{
        MessageID: messageID,
        Success:   true,
        Timestamp: time.Now(),
    }, nil
}

// connectSMTP establishes SMTP connection
func (s *SMTPClient) connectSMTP(ctx context.Context) (*smtp.Client, error) {
    address := fmt.Sprintf("%s:%d", s.config.Host, s.config.Port)
    
    // Create connection
    conn, err := smtp.Dial(address)
    if err != nil {
        return nil, fmt.Errorf("dial failed: %w", err)
    }

    // Start TLS if required
    if s.config.UseTLS {
        tlsConfig := &tls.Config{
            ServerName:         s.config.Host,
            InsecureSkipVerify: s.config.InsecureSkipVerify,
        }

        if err := conn.StartTLS(tlsConfig); err != nil {
            conn.Close()
            return nil, fmt.Errorf("StartTLS failed: %w", err)
        }
    }

    // Authenticate
    if s.auth != nil {
        if err := conn.Auth(s.auth); err != nil {
            conn.Close()
            return nil, fmt.Errorf("authentication failed: %w", err)
        }
    }

    return conn, nil
}

// buildMessage constructs the email message
func (s *SMTPClient) buildMessage(email *EmailMessage) ([]byte, error) {
    var buf bytes.Buffer

    // Headers
    buf.WriteString(fmt.Sprintf("From: %s <%s>\r\n", s.config.FromName, s.config.From))
    buf.WriteString(fmt.Sprintf("To: %s\r\n", strings.Join(email.To, ", ")))
    
    if len(email.CC) > 0 {
        buf.WriteString(fmt.Sprintf("CC: %s\r\n", strings.Join(email.CC, ", ")))
    }
    
    buf.WriteString(fmt.Sprintf("Subject: %s\r\n", email.Subject))
    buf.WriteString(fmt.Sprintf("Date: %s\r\n", time.Now().Format(time.RFC1123Z)))
    buf.WriteString(fmt.Sprintf("Message-ID: <%s>\r\n", s.generateMessageID()))
    buf.WriteString("MIME-Version: 1.0\r\n")

    // Priority header
    switch email.Priority {
    case "high":
        buf.WriteString("X-Priority: 1\r\n")
        buf.WriteString("X-MSMail-Priority: High\r\n")
    case "low":
        buf.WriteString("X-Priority: 5\r\n")
        buf.WriteString("X-MSMail-Priority: Low\r\n")
    }

    // Custom headers
    for key, value := range email.Headers {
        buf.WriteString(fmt.Sprintf("%s: %s\r\n", key, value))
    }

    // Handle multipart message (HTML + text + attachments)
    if email.HTMLBody != "" || len(email.Attachments) > 0 {
        boundary := s.generateBoundary()
        buf.WriteString(fmt.Sprintf("Content-Type: multipart/mixed; boundary=\"%s\"\r\n", boundary))
        buf.WriteString("\r\n")

        // Text/HTML parts
        if email.Body != "" || email.HTMLBody != "" {
            altBoundary := s.generateBoundary()
            buf.WriteString(fmt.Sprintf("--%s\r\n", boundary))
            buf.WriteString(fmt.Sprintf("Content-Type: multipart/alternative; boundary=\"%s\"\r\n", altBoundary))
            buf.WriteString("\r\n")

            // Plain text part
            if email.Body != "" {
                buf.WriteString(fmt.Sprintf("--%s\r\n", altBoundary))
                buf.WriteString("Content-Type: text/plain; charset=UTF-8\r\n")
                buf.WriteString("Content-Transfer-Encoding: quoted-printable\r\n")
                buf.WriteString("\r\n")
                buf.WriteString(s.encodeQuotedPrintable(email.Body))
                buf.WriteString("\r\n")
            }

            // HTML part
            if email.HTMLBody != "" {
                buf.WriteString(fmt.Sprintf("--%s\r\n", altBoundary))
                buf.WriteString("Content-Type: text/html; charset=UTF-8\r\n")
                buf.WriteString("Content-Transfer-Encoding: quoted-printable\r\n")
                buf.WriteString("\r\n")
                buf.WriteString(s.encodeQuotedPrintable(email.HTMLBody))
                buf.WriteString("\r\n")
            }

            buf.WriteString(fmt.Sprintf("--%s--\r\n", altBoundary))
        }

        // Attachments
        for _, attachment := range email.Attachments {
            buf.WriteString(fmt.Sprintf("--%s\r\n", boundary))
            
            if attachment.Inline {
                buf.WriteString(fmt.Sprintf("Content-Type: %s; name=\"%s\"\r\n", attachment.ContentType, attachment.Filename))
                buf.WriteString("Content-Transfer-Encoding: base64\r\n")
                buf.WriteString(fmt.Sprintf("Content-Disposition: inline; filename=\"%s\"\r\n", attachment.Filename))
                buf.WriteString(fmt.Sprintf("Content-ID: <%s>\r\n", attachment.Filename))
            } else {
                buf.WriteString(fmt.Sprintf("Content-Type: %s; name=\"%s\"\r\n", attachment.ContentType, attachment.Filename))
                buf.WriteString("Content-Transfer-Encoding: base64\r\n")
                buf.WriteString(fmt.Sprintf("Content-Disposition: attachment; filename=\"%s\"\r\n", attachment.Filename))
            }
            buf.WriteString("\r\n")
            
            // Encode attachment data
            encoded := base64.StdEncoding.EncodeToString(attachment.Data)
            for i := 0; i < len(encoded); i += 76 {
                end := i + 76
                if end > len(encoded) {
                    end = len(encoded)
                }
                buf.WriteString(encoded[i:end] + "\r\n")
            }
        }

        buf.WriteString(fmt.Sprintf("--%s--\r\n", boundary))
    } else {
        // Simple text message
        buf.WriteString("Content-Type: text/plain; charset=UTF-8\r\n")
        buf.WriteString("Content-Transfer-Encoding: quoted-printable\r\n")
        buf.WriteString("\r\n")
        buf.WriteString(s.encodeQuotedPrintable(email.Body))
    }

    return buf.Bytes(), nil
}

// SendBatchEmails sends multiple emails in batch
func (s *SMTPClient) SendBatchEmails(ctx context.Context, emails []*EmailMessage) ([]*EmailResponse, error) {
    if len(emails) == 0 {
        return nil, fmt.Errorf("no emails to send")
    }

    var responses []*EmailResponse
    batchSize := s.config.BatchSize
    if batchSize <= 0 {
        batchSize = 100 // Default batch size
    }

    // Process in batches
    for i := 0; i < len(emails); i += batchSize {
        end := i + batchSize
        if end > len(emails) {
            end = len(emails)
        }

        batch := emails[i:end]
        batchResponses := make([]*EmailResponse, len(batch))

        // Send emails in parallel within batch
        var wg sync.WaitGroup
        for j, email := range batch {
            wg.Add(1)
            go func(index int, msg *EmailMessage) {
                defer wg.Done()
                response, err := s.SendEmail(ctx, msg)
                if err != nil && response == nil {
                    response = &EmailResponse{
                        Success:   false,
                        Error:     err.Error(),
                        Timestamp: time.Now(),
                    }
                }
                batchResponses[index] = response
            }(j, email)
        }

        wg.Wait()
        responses = append(responses, batchResponses...)

        // Rate limiting between batches
        if i+batchSize < len(emails) {
            time.Sleep(1 * time.Second)
        }
    }

    return responses, nil
}

// Template management

// loadTemplates loads email templates from files
func (s *SMTPClient) loadTemplates() error {
    // This is a placeholder - implement template loading from files
    // Templates should be stored in a templates directory
    templateDir := "templates/email"
    
    templates := map[string]string{
        "welcome": `
Subject: Welcome to {{.AppName}}!

Hello {{.Name}},

Welcome to {{.AppName}}! We're excited to have you on board.

Best regards,
The {{.AppName}} Team
`,
        "notification": `
Subject: {{.Title}}

Hello {{.Name}},

{{.Message}}

{{if .ActionURL}}
[{{.ActionText}}]({{.ActionURL}})
{{end}}

Best regards,
The {{.AppName}} Team
`,
    }

    for name, content := range templates {
        tmpl, err := template.New(name).Parse(content)
        if err != nil {
            return fmt.Errorf("failed to parse template %s: %w", name, err)
        }
        s.templates[name] = tmpl
    }

    log.Printf("Loaded %d email templates", len(s.templates))
    return nil
}

// renderTemplate renders email template with data
func (s *SMTPClient) renderTemplate(email *EmailMessage) error {
    tmpl, exists := s.templates[email.Template]
    if !exists {
        return fmt.Errorf("template %s not found", email.Template)
    }

    var buf bytes.Buffer
    if err := tmpl.Execute(&buf, email.TemplateData); err != nil {
        return fmt.Errorf("template execution failed: %w", err)
    }

    content := buf.String()
    
    // Parse subject and body from template output
    lines := strings.Split(content, "\n")
    var subjectFound bool
    var bodyLines []string

    for _, line := range lines {
        line = strings.TrimSpace(line)
        if strings.HasPrefix(line, "Subject:") && !subjectFound {
            email.Subject = strings.TrimSpace(strings.TrimPrefix(line, "Subject:"))
            subjectFound = true
        } else if line != "" || subjectFound {
            if subjectFound {
                bodyLines = append(bodyLines, line)
            }
        }
    }

    email.Body = strings.Join(bodyLines, "\n")
    return nil
}

// Utility methods

func (s *SMTPClient) validateEmail(email *EmailMessage) error {
    if len(email.To) == 0 {
        return fmt.Errorf("at least one recipient is required")
    }
    if email.Subject == "" {
        return fmt.Errorf("subject is required")
    }
    if email.Body == "" && email.HTMLBody == "" {
        return fmt.Errorf("email body is required")
    }
    return nil
}

func (s *SMTPClient) generateMessageID() string {
    return fmt.Sprintf("%d.%s@%s", time.Now().UnixNano(), randomString(8), s.config.Host)
}

func (s *SMTPClient) generateBoundary() string {
    return fmt.Sprintf("boundary_%d_%s", time.Now().UnixNano(), randomString(16))
}

func (s *SMTPClient) encodeQuotedPrintable(text string) string {
    // Simple quoted-printable encoding
    var result strings.Builder
    for _, r := range text {
        if r == '\n' {
            result.WriteString("\r\n")
        } else if r > 127 || r == '=' {
            result.WriteString(fmt.Sprintf("=%02X", r))
        } else {
            result.WriteRune(r)
        }
    }
    return result.String()
}

func (s *SMTPClient) updateMetrics(response *EmailResponse, err error) {
    s.metrics.mu.Lock()
    defer s.metrics.mu.Unlock()

    s.metrics.EmailsSent++
    if err != nil || !response.Success {
        s.metrics.EmailsFailed++
    } else {
        s.metrics.EmailsDelivered++
    }

    // Update bounce rate
    if s.metrics.EmailsSent > 0 {
        s.metrics.BounceRate = float64(s.metrics.EmailsFailed) / float64(s.metrics.EmailsSent) * 100
    }
}

func (s *SMTPClient) healthCheckRoutine() {
    ticker := time.NewTicker(60 * time.Second)
    defer ticker.Stop()

    for range ticker.C {
        s.performHealthCheck()
    }
}

func (s *SMTPClient) performHealthCheck() {
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()

    // Try to connect to SMTP server
    conn, err := s.connectSMTP(ctx)
    
    s.mu.Lock()
    s.metrics.mu.Lock()
    
    if err != nil {
        s.healthy = false
        log.Printf("SMTP health check failed: %v", err)
    } else {
        s.healthy = true
        conn.Quit()
    }
    
    s.metrics.LastHealthCheck = time.Now()
    s.metrics.mu.Unlock()
    s.mu.Unlock()
}

// IsHealthy returns current health status
func (s *SMTPClient) IsHealthy() bool {
    s.mu.RLock()
    defer s.mu.RUnlock()
    return s.healthy
}

// GetMetrics returns current metrics
func (s *SMTPClient) GetMetrics() *EmailMetrics {
    s.metrics.mu.RLock()
    defer s.metrics.mu.RUnlock()

    return &EmailMetrics{
        EmailsSent:      s.metrics.EmailsSent,
        EmailsDelivered: s.metrics.EmailsDelivered,
        EmailsFailed:    s.metrics.EmailsFailed,
        BounceRate:      s.metrics.BounceRate,
        LastHealthCheck: s.metrics.LastHealthCheck,
    }
}

// Rate limiter implementation

// Allow checks if sending is allowed under rate limit
func (rl *EmailRateLimiter) Allow() bool {
    rl.mu.Lock()
    defer rl.mu.Unlock()

    now := time.Now()
    
    // Clean old entries (older than 1 minute)
    cutoff := now.Add(-time.Minute)
    var validEntries []time.Time
    for _, t := range rl.sent {
        if t.After(cutoff) {
            validEntries = append(validEntries, t)
        }
    }
    rl.sent = validEntries

    // Check if under limit
    if len(rl.sent) < rl.maxPerMinute {
        rl.sent = append(rl.sent, now)
        return true
    }

    return false
}

func randomString(length int) string {
    const charset = "abcdefghijklmnopqrstuvwxyz0123456789"
    b := make([]byte, length)
    for i := range b {
        b[i] = charset[time.Now().UnixNano()%int64(len(charset))]
    }
    return string(b)
}