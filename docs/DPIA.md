# Data Protection Impact Assessment (DPIA)

**Regulation:** General Data Protection Regulation (EU) 2016/679, Article 35
**Trigger:** Art. 35(3)(c) -- Systematic monitoring of publicly accessible areas
**Supervisory Authority:** Berliner Beauftragte fuer Datenschutz und Informationsfreiheit
**Document Version:** 1.0
**Date of Assessment:** [DD/MM/YYYY]

---

## 1. Project Description

**Project Name:** Signalstream Social Intelligence Platform

**Purpose of Processing:**
Signalstream is a social intelligence platform that collects publicly available posts from Reddit and X/Twitter, performs AI-powered sentiment analysis and thematic categorisation, and generates structured PDF reports summarising public discourse on configurable topics.

**Processing Activities:**

1. Automated collection of public social media posts via official platform APIs (Reddit PRAW, X/Twitter API).
2. Natural language processing to determine sentiment polarity and extract thematic clusters.
3. Aggregation of engagement metrics (upvotes, comment counts) for trend analysis.
4. Generation of PDF reports containing analytical findings.
5. Optional delivery of reports to voluntarily provided email addresses.

**Data Subjects:** Authors of publicly accessible social media posts on Reddit and X/Twitter. No data is collected from private accounts, direct messages, or non-public spaces.

**Data Recipients:** The controller (platform operator) and, where applicable, authorised users of the web interface who initiate analyses.

---

## 2. Legal Basis for Processing

**Primary Legal Basis:** Article 6(1)(f) GDPR -- Legitimate interests pursued by the controller.

**Legitimate Interest:** Understanding public discourse and sentiment trends on matters of public interest, market research, and reputational analysis through aggregation and anonymisation of publicly available statements.

**Balancing Test (Art. 6(1)(f)):**

| Factor | Assessment |
|---|---|
| Nature of the interest | Legitimate commercial and research interest in analysing publicly shared opinions. |
| Impact on data subjects | Low -- posts are already publicly accessible; processing adds analytical layer without increasing exposure. |
| Reasonable expectations | Users who post publicly on Reddit and X/Twitter reasonably expect their posts to be read and indexed by third parties, including via official APIs. |
| Safeguards applied | Username hashing, URL redaction, no profile scraping, configurable data retention (see Sections 4--5). |
| Proportionality | Processing is limited to publicly available content; no special category data is deliberately processed; pseudonymisation measures are applied at collection time. |

**Conclusion:** The legitimate interest of the controller is not overridden by the interests, rights, or freedoms of the data subjects, given the public nature of the source data and the technical safeguards applied.

**Email Processing (Report Delivery):** Where a user voluntarily provides an email address for report delivery, processing is based on Article 6(1)(a) GDPR -- consent, freely given at the point of submission.

---

## 3. Categories of Personal Data Collected

| Data Category | Source | Classification | Treatment |
|---|---|---|---|
| Post content (titles, body text) | Reddit, X/Twitter | Public personal data | Stored for analysis; no modification |
| Usernames | Reddit, X/Twitter | Public personal data | Hashed with per-instance SHA-256 salt before storage |
| Post URLs | Reddit, X/Twitter | Public personal data | Redacted at collection time (scheme://domain/[redacted]) |
| Engagement metrics (upvotes, comments) | Reddit, X/Twitter | Public aggregate data | Stored as numerical aggregates only |
| Email addresses | Voluntary user input | Private personal data | Encrypted at rest with Fernet symmetric encryption |

**Special Categories (Art. 9):** The platform does not deliberately collect or process special category data. Sentiment analysis operates on aggregate patterns and does not classify individuals by political opinion, religious belief, health status, or other Art. 9 categories.

---

## 4. Data Minimisation Measures (Art. 5(1)(c))

The following measures ensure that processing is limited to what is necessary in relation to the purposes for which data are processed:

- **Username Pseudonymisation:** All usernames are hashed using SHA-256 with a per-instance cryptographic salt before storage. The salt is stored locally in `.hash_salt` and is excluded from version control. Original usernames are not retained.
- **URL Redaction:** Post URLs are stripped of identifying path components at collection time via the `_strip_pii_url` function, retaining only the scheme and domain (e.g., `https://reddit.com/[redacted]`).
- **No Profile Scraping:** The platform does not collect user profile information, follower/following relationships, biographical data, or profile images.
- **No Private Content:** Direct messages, private community posts, and content from non-public accounts are never accessed or processed.
- **Configurable Data Retention:** Stored analysis data is subject to configurable retention periods, after which it is purged.

---

## 5. Technical and Organisational Measures (Art. 32)

### 5.1 Encryption and Access Control

| Measure | Implementation |
|---|---|
| Encryption at rest | Email addresses encrypted using Fernet (symmetric, AES-128-CBC with HMAC-SHA256) |
| Authentication | HMAC-based token authentication for web interface access |
| CSRF protection | Enabled on all state-changing endpoints |
| API key management | All API keys (Reddit, X/Twitter, Ollama) stored exclusively as environment variables; never hardcoded or committed to version control |
| Version control hygiene | `.gitignore` configured to exclude `.env`, `.hash_salt`, API keys, and other sensitive files |

### 5.2 Availability and Resilience

| Measure | Implementation |
|---|---|
| Rate limiting | Maximum 3 analyses per 10-minute window to prevent abuse and ensure platform API compliance |
| API access | Reddit data accessed via PRAW (official API wrapper); `public_json` endpoint blocked for commercial use to ensure Terms of Service compliance |

### 5.3 Organisational Measures

- Access to the platform is restricted to authenticated users.
- Sensitive configuration is separated from application code.
- Security-relevant dependencies are subject to periodic review.

---

## 6. Risk Assessment

| # | Risk | Likelihood | Severity | Overall | Mitigation | Residual Risk |
|---|---|---|---|---|---|---|
| R1 | **Re-identification** of data subjects through matching post content against original public sources | Medium | Medium | Medium | URL redaction removes direct links; username hashing prevents casual identification; post content alone, while theoretically matchable, requires active effort against the original platform | Low |
| R2 | **Unauthorised access** to stored analysis data | Low | Medium | Low | HMAC-based authentication; CSRF protection; rate limiting restricts brute-force attempts | Low |
| R3 | **Data breach** exposing stored email addresses | Low | High | Medium | Email addresses encrypted at rest with Fernet; decryption key managed separately from application data | Low |
| R4 | **Platform Terms of Service violation** leading to data access revocation or legal action | Low | Medium | Low | Reddit data collected via PRAW (official API); `public_json` endpoint explicitly blocked for commercial use; processing limited to public posts within API rate limits | Low |
| R5 | **Excessive data retention** beyond processing purpose | Medium | Low | Low | Configurable retention periods; deletion capability available | Low |

**Overall Risk Rating:** Low, after application of the mitigations described above. Residual risks are acceptable and proportionate to the processing purpose.

---

## 7. Data Subject Rights (Chapter III GDPR)

The controller shall facilitate the exercise of data subject rights in accordance with Articles 12--22 GDPR:

| Right | Implementation |
|---|---|
| **Right of access (Art. 15)** | Data subjects may request confirmation of whether their post content has been processed. Due to username hashing, identification requires the data subject to provide their original username for hash verification. |
| **Right to erasure (Art. 17)** | Data subjects may request deletion of any analysed posts containing their content. Upon verified request, corresponding records are removed from all storage. |
| **Right to restriction (Art. 18)** | Processing of specific content can be restricted upon request pending resolution of an objection. |
| **Right to object (Art. 21)** | Data subjects may object to processing based on legitimate interest. The controller will cease processing unless compelling legitimate grounds are demonstrated. |
| **Right to information (Art. 13/14)** | The methodology section of generated reports discloses data sources, processing logic, and the analytical methods applied. |

**Contact for Rights Requests:** [Developer/Controller email address]

**Response Timeline:** All requests will be acknowledged within 72 hours and fulfilled within one calendar month in accordance with Art. 12(3) GDPR.

---

## 8. Consultation

**Supervisory Authority Consultation (Art. 36):** Based on the risk assessment in Section 6, the residual risk after mitigation is assessed as low. Prior consultation with the Berliner Beauftragte fuer Datenschutz und Informationsfreiheit under Art. 36(1) is therefore not required at this time. This determination shall be revisited upon any material change to processing activities or risk profile.

---

## 9. Review Schedule

This DPIA shall be reviewed:

- **Annually** from the date of initial approval, or
- **Upon any significant change** to processing activities, including but not limited to:
  - Addition of new data sources or social media platforms
  - Changes to the categories of personal data collected
  - Introduction of new analytical methods (e.g., facial recognition, biometric processing)
  - Changes to data storage architecture or retention policies
  - Material changes to technical or organisational security measures
  - Changes in applicable legal requirements

The review shall assess whether the processing remains compliant with this assessment and whether risk levels have changed.

---

## 10. Approval

| Role | Name | Signature | Date |
|---|---|---|---|
| **Data Controller** | [Full name] | ___________________ | [DD/MM/YYYY] |
| **Data Protection Officer** | [Full name, if appointed] | ___________________ | [DD/MM/YYYY] |
| **Technical Lead** | [Full name] | ___________________ | [DD/MM/YYYY] |

**Note:** Where a Data Protection Officer has not been formally appointed under Art. 37 GDPR, the controller retains full responsibility for ensuring compliance with this assessment.

---

*This document constitutes a Data Protection Impact Assessment under Article 35 of the General Data Protection Regulation (EU) 2016/679. It is a living document and shall be updated in accordance with the review schedule set out in Section 9.*
