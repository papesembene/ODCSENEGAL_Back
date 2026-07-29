import http from "k6/http"
import { check, sleep } from "k6"
import { SharedArray } from "k6/data"

const BASE_URL = __ENV.ODC_LOAD_BASE_URL || "http://127.0.0.1:5000"
const TEST_ID = (__ENV.ODC_LOAD_TEST_ID || "").trim()
const CANDIDATES_CSV = __ENV.ODC_LOAD_CANDIDATES_CSV || "load_tests/candidates.csv"
const SUBMIT_RESULTS = __ENV.ODC_LOAD_SUBMIT_RESULTS === "1"
const SAVE_DRAFT = __ENV.ODC_LOAD_SAVE_DRAFT !== "0"
const SCORE = Number(__ENV.ODC_LOAD_SCORE || 100)
const PASSING_SCORE = Number(__ENV.ODC_LOAD_PASSING_SCORE || 70)

export const options = {
  scenarios: {
    online_test: {
      executor: "ramping-vus",
      stages: [
        { duration: __ENV.ODC_LOAD_RAMP_UP || "30s", target: Number(__ENV.ODC_LOAD_USERS || 50) },
        { duration: __ENV.ODC_LOAD_DURATION || "2m", target: Number(__ENV.ODC_LOAD_USERS || 50) },
        { duration: __ENV.ODC_LOAD_RAMP_DOWN || "15s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{name:public_metadata}": ["p(95)<800"],
    "http_req_duration{name:verify_access}": ["p(95)<1000"],
    "http_req_duration{name:save_draft}": ["p(95)<1200"],
    "http_req_duration{name:submit_result}": ["p(95)<1500"],
  },
}

const candidates = new SharedArray("online-test-candidates", () => {
  const rows = parseCsv(open(CANDIDATES_CSV))
  const validRows = rows
    .map((row) => ({
      name: (row.name || row.nom || "").trim() || "Candidat test",
      email: (row.email || "").trim().toLowerCase(),
      phone: (row.phone || row.telephone || "").trim(),
    }))
    .filter((candidate) => candidate.email && candidate.phone)

  if (!validRows.length) {
    throw new Error("CSV candidats invalide. Colonnes attendues: name,email,phone")
  }

  return validRows
})

export function setup() {
  if (!TEST_ID) {
    throw new Error("ODC_LOAD_TEST_ID est requis")
  }

  return { testId: TEST_ID }
}

export default function ({ testId }) {
  const candidate = candidates[(__VU - 1) % candidates.length]
  const metadata = readPublicMetadata(testId)
  sleep(randomDelay(0.2, 0.8))

  const access = verifyAccess(testId, candidate)
  if (!access) {
    sleep(randomDelay(0.5, 1.2))
    return
  }

  if (SAVE_DRAFT) {
    saveDraft(testId, candidate, metadata)
    sleep(randomDelay(0.3, 1.0))
  }

  if (SUBMIT_RESULTS) {
    submitResult(testId, candidate, metadata)
  }

  sleep(randomDelay(0.5, 2.0))
}

function readPublicMetadata(testId) {
  const response = http.get(`${BASE_URL}/api/admin/tests/${testId}/public`, {
    tags: { name: "public_metadata" },
  })

  check(response, {
    "metadata 200": (res) => res.status === 200,
    "metadata success": (res) => safeJson(res).success === true,
  })

  const payload = safeJson(response)
  return payload.data || {
    title: "Test de charge",
    referentiel: "Non renseigne",
    passingScore: PASSING_SCORE,
    questions: [],
  }
}

function verifyAccess(testId, candidate) {
  const response = http.post(
    `${BASE_URL}/api/admin/tests/${testId}/verify-access`,
    JSON.stringify({
      email: candidate.email,
      phone: candidate.phone,
    }),
    {
      headers: { "Content-Type": "application/json" },
      tags: { name: "verify_access" },
    },
  )

  const payload = safeJson(response)
  const ok = check(response, {
    "verify 200": (res) => res.status === 200,
    "verify authorized": () => payload.authorized === true,
  })

  return ok && payload.authorized === true
}

function saveDraft(testId, candidate, metadata) {
  const response = http.put(
    `${BASE_URL}/api/admin/tests/${testId}/session-draft`,
    JSON.stringify({
      email: candidate.email,
      phone: candidate.phone,
      name: candidate.name,
      answers: buildAnswers(metadata.questions || []),
      lastQuestion: 0,
      remainingTime: Number(metadata.duration || 60) * 60,
    }),
    {
      headers: { "Content-Type": "application/json" },
      tags: { name: "save_draft" },
    },
  )

  check(response, {
    "draft 200": (res) => res.status === 200,
    "draft success": (res) => safeJson(res).success === true,
  })
}

function submitResult(testId, candidate, metadata) {
  const now = new Date()
  const response = http.post(
    `${BASE_URL}/api/admin/tests/results`,
    JSON.stringify({
      testId,
      testTitle: metadata.title || "Test de charge",
      referentiel: metadata.referentiel || "Non renseigne",
      candidate,
      answers: buildAnswers(metadata.questions || []),
      score: SCORE,
      status: SCORE >= PASSING_SCORE ? "admis" : "rejeté",
      passingScore: metadata.passingScore || PASSING_SCORE,
      totalQuestions: metadata.questions?.length || 0,
      answeredQuestions: metadata.questions?.length || 0,
      completedAt: now.toISOString(),
      submittedDate: now.toLocaleDateString("fr-FR"),
      submittedTime: now.toLocaleTimeString("fr-FR"),
    }),
    {
      headers: { "Content-Type": "application/json" },
      tags: { name: "submit_result" },
    },
  )

  check(response, {
    "submit 200/201": (res) => [200, 201].includes(res.status),
    "submit success": (res) => safeJson(res).success === true,
  })
}

function buildAnswers(questions) {
  return questions.reduce((answers, question, index) => {
    if (question.type === "qcm_multiple") {
      answers[index] = question.correctAnswers || []
      return answers
    }

    if (question.type === "texte_libre") {
      answers[index] = "Réponse simulée par test de charge"
      return answers
    }

    answers[index] = question.correctAnswer ?? 0
    return answers
  }, {})
}

function parseCsv(content) {
  const lines = content.split(/\r?\n/).filter((line) => line.trim())
  const headers = splitCsvLine(lines.shift() || "").map((header) => header.trim())

  return lines.map((line) => {
    const values = splitCsvLine(line)
    return headers.reduce((row, header, index) => {
      row[header] = values[index] || ""
      return row
    }, {})
  })
}

function splitCsvLine(line) {
  const values = []
  let current = ""
  let quoted = false

  for (const char of line) {
    if (char === '"') {
      quoted = !quoted
      continue
    }

    if (char === "," && !quoted) {
      values.push(current)
      current = ""
      continue
    }

    current += char
  }

  values.push(current)
  return values
}

function safeJson(response) {
  try {
    return response.json()
  } catch {
    return {}
  }
}

function randomDelay(min, max) {
  return Math.random() * (max - min) + min
}
