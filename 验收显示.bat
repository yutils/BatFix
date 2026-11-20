@echo off
chcp 65001 >nul
echo ==========================================
echo   BatFix 验收显示测试 
echo ==========================================
echo 中文测试：你好，世界！ 
echo 特殊符号：「」【】、；：“”‘’《》 
echo 表情符号：😀 🎉 🍄 
set "v=中文变量值"
echo 变量展开：%v%
if exist "%windir%" (
    echo if 括号块内中文正常 
)
for %%i in (一 二 三) do echo 循环第 %%i 次 
echo 以上中文、标点、变量、if 和 for 都正常，说明转换成功 
pause
