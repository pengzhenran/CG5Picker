; =============================================================================
;  Inno Setup script —— CG5Picker v1.0（CG5 数据挑选）
; =============================================================================
;  用法（推荐直接跑一键脚本，它会把路径按实际构建根目录注入）：
;
;      powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1
;
;  或者手工两步：
;    1) 先出 PyInstaller 目录包（在 CG5Picker\ 下执行）：
;         pyinstaller --clean --noconfirm packaging\cg5picker.spec
;       → <构建根>\dist\CG5Picker\CG5Picker.exe + _internal\
;    2) 再编译本脚本：
;         ISCC.exe /DProjDir=<项目目录> /DBuildRoot=<构建根> installer_cg5picker.iss
;       → <构建根>\dist\CG5Picker_Setup_v1.0.0.exe
;
;  发行包内容：
;    CG5Picker.exe + _internal\   运行所需全部组件（Python 运行、Qt、绘图库…）
;    _internal\docs\              使用说明.html + 配图 + 公众号二维码
;    _internal\licenses\          NOTICE + LGPL-3.0 + GPL-3.0
;    _internal\resources\         程序图标
;    source\                      软件运行代码（pickersrc\）+ README + LICENSE
;    config\                      **不随包**：运行期由程序自己创建（放参数设置的记忆）
;
;  ★ 许可合规：安装向导带**许可页**（MIT 全文，必须同意才能装）与
;    **安装前信息页**（第三方组件与 LGPLv3 声明），对应 LGPLv3 的"显著声明"义务。
; =============================================================================

; 路径与版本：允许命令行用 /D 覆盖（避免中文路径 + 相对路径解析的坑）
#ifndef ProjDir
  #define ProjDir "D:\CG5Picker_build\project"
#endif
#ifndef BuildRoot
  #define BuildRoot "D:\CG5Picker_build"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName       "CG5Picker"
#define MyAppNameCN     "CG5 数据挑选"
#define MyAppPublisher  "彭桢燃  Zhenran Peng  (China University of Geosciences, Wuhan)"
#define MyAppURL        "https://www.cug.edu.cn"
#define MyAppExeName    "CG5Picker.exe"
#define SourceDir       BuildRoot + "\dist\CG5Picker"
#define OutputDir       BuildRoot + "\dist"
#define IconFile        ProjDir + "\resources\cg5picker.ico"

[Setup]
; 每次发布换一个 GUID：Inno Setup 菜单 Tools -> Generate GUID
AppId={{7C41A9E2-2D6B-4F58-9E31-1A5B7C0D4E88}
AppName={#MyAppName} {#MyAppNameCN}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppNameCN} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; 默认按用户安装（不弹管理员）：装到 %LOCALAPPDATA%\Programs\CG5Picker，
; 这样安装目录**可写** —— 本软件把参数设置/条件组合存在安装目录的 config\ 下。
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=CG5Picker_Setup_v{#MyAppVersion}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppNameCN}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
ShowLanguageDialog=auto
; ★ 安装程序**自己**的版本资源（右键属性里看到的那一栏）—— 版权/公司跟 appinfo 一致
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} {#MyAppNameCN} 安装程序 / Setup
VersionInfoCopyright=Copyright (c) 2026 彭桢燃 (Zhenran Peng)  MIT 许可
VersionInfoProductName={#MyAppName} {#MyAppNameCN}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoTextVersion={#MyAppVersion}
; ★ 许可页（MIT 全文）与安装前信息页（第三方组件声明）
LicenseFile={#ProjDir}\LICENSE.txt
InfoBeforeFile={#ProjDir}\licenses\NOTICE.txt
; 安装前请用户关掉正在运行的 CG5Picker，避免文件占用装不上
CloseApplications=yes
RestartApplications=no

[Languages]
; Inno Setup 官方安装包**不带**简体中文语言文件，构建脚本会把
; packaging\languages\ChineseSimplified.isl 复制到 <Inno Setup>\Languages\；
; 只有真找到该文件时才加中文，否则退回英文 —— 用 /DHaveChinese=1 控制。
#ifdef HaveChinese
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 / Create a &desktop shortcut"; GroupDescription: "附加任务 / Additional shortcuts:"; Flags: checkedonce

[Files]
; --- 程序本体（PyInstaller onedir 输出） -----------------------------------
Source: "{#SourceDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; --- 随包附源码（便于用户核对与复现；也是 LGPLv3 相关声明的载体） ----------
Source: "{#ProjDir}\pickersrc\*";  DestDir: "{app}\source\pickersrc";  Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"
Source: "{#ProjDir}\main.py";      DestDir: "{app}\source"; Flags: ignoreversion
Source: "{#ProjDir}\README.md";    DestDir: "{app}\source"; Flags: ignoreversion
Source: "{#ProjDir}\LICENSE.txt";  DestDir: "{app}\source"; Flags: ignoreversion
Source: "{#ProjDir}\licenses\*";   DestDir: "{app}\source\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjDir}\docs\*";       DestDir: "{app}\source\docs"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjDir}\resources\*";  DestDir: "{app}\source\resources"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjDir}\packaging\*";  DestDir: "{app}\source\packaging"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"

[Icons]
Name: "{group}\{#MyAppName} {#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\使用说明 (HTML)"; Filename: "{app}\_internal\docs\使用说明.html"
Name: "{group}\作者信息 / 关于"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--version"
Name: "{group}\许可与第三方声明"; Filename: "{app}\_internal\licenses\NOTICE.txt"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName} {#MyAppNameCN}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\_internal\docs\使用说明.html"; Description: "打开使用说明"; Flags: shellexec nowait postinstall skipifsilent unchecked

[UninstallDelete]
; 只清掉可能残留的缓存；**config\ 里的参数设置与条件组合会随卸载一起删除**
; （它们就在安装目录下 —— 想保留请卸载前把 config\ 备份出去）
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
