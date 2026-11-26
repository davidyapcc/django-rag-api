{{- define "rag.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "rag.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "rag.labels" -}}
{{ include "rag.selectorLabels" . }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "rag.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- end -}}

{{/* Env shared by the app pods and the migration Job. */}}
{{- define "rag.env" -}}
envFrom:
  - secretRef:
      name: {{ .Values.existingSecret }}
env:
  - name: ALLOWED_HOSTS
    value: {{ .Values.host | quote }}
  {{- range $k, $v := .Values.env }}
  - name: {{ $k }}
    value: {{ $v | quote }}
  {{- end }}
{{- end -}}

{{- define "rag.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 1000 # the image's `app` user; numeric so the kubelet can verify non-root
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "rag.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end -}}
