"""HTML template for online-test invitations."""

from html import escape


def build_test_invitation_html(
    *,
    candidate_email,
    candidate_name,
    candidate_phone,
    candidate_gender,
    test_title,
    test_date,
    test_time,
    test_duration,
    test_link,
):
    suffix = _gender_suffix(candidate_gender)
    values = {
        "candidate_email": escape(str(candidate_email)),
        "candidate_name": escape(str(candidate_name)),
        "candidate_phone": escape(str(candidate_phone)),
        "test_title": escape(str(test_title)),
        "test_date": escape(str(test_date)),
        "test_time": escape(str(test_time)),
        "test_duration": escape(str(test_duration)),
        "test_link": escape(str(test_link), quote=True),
        "suffix": suffix,
    }
    return _TEMPLATE.format(**values)


def _gender_suffix(gender):
    normalized = str(gender or "").strip().lower()
    if not normalized:
        return "(e)"
    if normalized in {"f", "femme", "female", "femenin", "féminin"}:
        return "e"
    return ""


_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{ margin:0; background:#f5f5f5; color:#333;
      font-family:Arial,sans-serif; line-height:1.6; }}
    .wrapper {{ padding:32px 16px; }}
    .card {{ max-width:600px; margin:auto; background:#fff; }}
    .header,.content,.footer {{ padding:28px; }}
    .header {{ text-align:center; border-bottom:4px solid #ff7900; }}
    .header img {{ width:190px; max-width:100%; }}
    h1 {{ font-size:26px; line-height:1.25; }}
    h2 {{ color:#ff7900; font-size:18px; }}
    .details {{ border:2px solid #ff7900; border-radius:8px;
      padding:22px; margin:24px 0; }}
    .row {{ margin:10px 0; }}
    .label {{ font-weight:700; }}
    .credential {{ color:#d95f00; font-weight:700; }}
    .button {{ display:inline-block; margin-top:20px; padding:13px 28px;
      border-radius:6px; background:#ff7900; color:#000;
      font-weight:700; text-decoration:none; }}
    .warning {{ padding:14px; background:#fff3cd;
      border-left:4px solid #ffc107; }}
    .footer {{ background:#f8f9fa; text-align:center;
      color:#666; font-size:12px; }}
  </style>
</head>
<body>
  <div class="wrapper"><div class="card">
    <div class="header">
      <img src="https://orangedigitalcenter.sn/Logotest.png"
        alt="Orange Digital Center">
    </div>
    <div class="content">
      <h1>Merci de vous être inscrit{suffix}, {candidate_name} !</h1>
      <p><strong>Information importante :</strong> votre groupe est
        programmé. Connectez-vous à l'heure indiquée et suivez les
        consignes affichées avant le test.</p>
      <div class="details">
        <h2>Détails du test</h2>
        <div class="row"><span class="label">Titre :</span>
          {test_title}</div>
        <div class="row"><span class="label">Date :</span>
          {test_date}</div>
        <div class="row"><span class="label">Heure :</span>
          {test_time}</div>
        <div class="row"><span class="label">Durée :</span>
          {test_duration} minutes</div>
        <h2>Vos identifiants</h2>
        <div class="row"><span class="label">Email :</span>
          <span class="credential">{candidate_email}</span></div>
        <div class="row"><span class="label">Téléphone :</span>
          <span class="credential">{candidate_phone}</span></div>
        <a href="{test_link}" class="button">Accéder au test</a>
      </div>
      <div class="warning"><strong>Important :</strong> le test est
        surveillé. Toute tentative de fraude peut entraîner son
        invalidation.</div>
    </div>
    <div class="footer">
      <p>Cet email a été envoyé automatiquement.</p>
      <p>Orange Digital Center - Sonatel</p>
      <p>+221 33 839 21 00 - 64 VDN, Dakar, Sénégal</p>
    </div>
  </div></div>
</body>
</html>"""
