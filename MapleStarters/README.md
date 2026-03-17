# Maple tiny starters

These scripts generate tiny test maps directly into this mod folder:

- Maps/Maggy/MapleStarter.bin
- Maps/Maggy/MapleStarterEntity.bin
- Maps/Maggy/MapleStarterRoute.bin

## Run

From PowerShell:

```powershell
& "C:\Users\Gabriel L\AppData\Local\Programs\Julia-1.12.5\bin\julia.exe" ".\MapleStarters\starter_minimal_map.jl"
& "C:\Users\Gabriel L\AppData\Local\Programs\Julia-1.12.5\bin\julia.exe" ".\MapleStarters\starter_entity_map.jl"
& "C:\Users\Gabriel L\AppData\Local\Programs\Julia-1.12.5\bin\julia.exe" ".\MapleStarters\starter_route_map.jl"
```

Or run the combined script (generate + preview):

```powershell
Push-Location ".\MapleStarters"
.\run_maple_and_preview.ps1 -Starter "starter_route_map.jl"
Pop-Location
```

## Loenn Launch (DLL-Checked)

Use the one-click Loenn launcher to verify required runtime files before startup:

```powershell
Push-Location ".\MapleStarters"
.\launch_loenn_checked.ps1 -LoennDir "C:\Users\Gabriel L\Desktop\Tools\Loenn" -ShowDlls
Pop-Location
```

If -LoennDir is omitted, the launcher checks:

- LOENN_DIR environment variable
- Auto-discovery under Desktop and Downloads (folders containing main.exe + required DLLs)

Required files in the Loenn folder:

- main.exe
- love.dll
- lua51.dll
- SDL2.dll

If any are missing, re-extract the full Windows release zip so all DLLs are next to main.exe.

## Combined Maple + Loenn Flow

You can launch Loenn automatically after generation/preview:

```powershell
Push-Location ".\MapleStarters"
.\run_maple_and_preview.ps1 -Starter "starter_route_map.jl" -LaunchLoenn -LoennDir "C:\Users\Gabriel L\Desktop\Tools\Loenn"
Pop-Location
```

Tip: set a persistent default path for Loenn:

```powershell
[Environment]::SetEnvironmentVariable("LOENN_DIR", "C:\Users\Gabriel L\Desktop\Tools\Loenn", "User")
```

After setting LOENN_DIR, you can omit -LoennDir.

## Notes

- Maple is already configured to use your local clone at C:/Users/Gabriel L/Desktop/celeste/Maple.
- Open the generated .bin files in your map tools, or load them through your mod chapter flow.
