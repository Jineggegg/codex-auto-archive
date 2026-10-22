# Codex Auto Archive

[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · **Español**

Administra el Archive nativo de Codex en lenguaje natural: inactividad, finalización explícita, PR/CI asociados, exclusiones, vista previa, restauración y comprobaciones locales. El programador no llama a ningún modelo. No elimina conversaciones ni modifica directamente los archivos internos de Codex.

**Límite actual:** en Codex 0.160.0, un App Server independiente no puede verificar de forma fiable la actividad de Desktop y no expone el estado de conversaciones fijadas. El complemento omite esos casos por seguridad. La instalación comienza en Dry Run; esta versión no garantiza archivado desatendido de Desktop. Consulta [compatibilidad](COMPATIBILITY.md).

Requisitos: Python 3.11+, uv y Codex CLI.

```bash
git clone https://github.com/Jineggegg/codex-auto-archive.git
cd codex-auto-archive
bash scripts/install.sh
```

En Windows: `powershell -ExecutionPolicy Bypass -File scripts/install.ps1`. Abre una conversación nueva y revisa los hooks con `/hooks`. Windows y WSL usan perfiles separados.

Ejemplos: «Archiva tras 7 días de inactividad», «Desactiva el archivado al terminar tareas», «Excluye este proyecto», «Previsualiza los próximos 7 días», «Restaura las conversaciones archivadas automáticamente ayer», «Cambia el idioma a español». Solo la activación explícita permite salir de Dry Run.

Valores iniciales: 30 días, disparadores de finalización/PR/CI/Issue/Goal desactivados individualmente, 30 minutos de espera, protección de conversaciones fijadas, 7 días de protección tras restaurar, revisión cada 60 minutos y máximo 20 hilos por revisión. Las operaciones por lotes requieren vista previa y confirmación. El hilo actual usa un ID exacto, espera al menos 60 segundos y debe estar inactivo.

Modos: conservador=90 días, estándar=30, agresivo=7. Idiomas: auto/en/zh-CN/ja/es. [Mantenimiento y desinstalación](../README.md).
