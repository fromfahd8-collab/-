[Setup]
AppName=KSO Download Turbo Ultra V1
AppVersion=1.0
DefaultDirName={autopf}\KSO Download Turbo Ultra V1
OutputDir=output
OutputBaseFilename=KSO_Download_Turbo_Ultra_V1_Setup
[Files]
Source: "dist\KSO_Download_Turbo_Ultra_V1.exe"; DestDir: "{app}"
Source: "lang.json"; DestDir: "{app}"
Source: "config.json"; DestDir: "{app}"