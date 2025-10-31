# -*- coding: utf-8 -*-
"""
Created on Wed Oct 22 14:20:54 2025

@author: maugut
"""

# Step 1: Navigate to your local repo
cd C:\\Users\\maugut\\Morice\\01_KTH\\16_Department\\Server\\Scripts

# Step 2: Initialize Git
!git init

# Step 3: Add the file to Git
!git add .

# Step 4: Commit the change
!git commit -m "Add app.py to docs folder"

# Step 5: Link Remote and Push
!git remote add origin https://github.com/morice333/workstation-queue-dashboard.git 
!git branch -M main
!git push origin main

#######################################
# If necessary needs to pull first
# !git pull origin main --allow-unrelated-histories
# If you want your local code to completely replace what’s on GitHub:
# !git push origin main --force
#######################################