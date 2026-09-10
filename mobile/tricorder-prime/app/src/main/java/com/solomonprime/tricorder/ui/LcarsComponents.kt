package com.solomonprime.tricorder.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.solomonprime.tricorder.ui.theme.*

/**
 * Get the icon/symbol for a given tab ID
 */
private fun getTabIcon(tabId: String): String = when (tabId) {
    "HOME" -> "⬡"
    "ENV" -> "◈"
    "GEO" -> "⊕"
    "EM" -> "∿"
    "ACO" -> "♪"
    "BIO" -> "♡"
    "RAD" -> "☢"
    "MAP" -> "⊞"
    "PIPE" -> "⊃"
    "RF" -> "⌁"
    "OBD" -> "⛽"
    "AI" -> "◇"
    else -> "◆"
}

@Composable
fun LcarsButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    color: Color = LcarsOrange,
    enabled: Boolean = true
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(topStart = 16.dp, bottomStart = 16.dp, topEnd = 8.dp, bottomEnd = 8.dp))
            .background(if (enabled) color else Color.Gray)
            .clickable(onClick = onClick, enabled = enabled)
            .padding(horizontal = 20.dp, vertical = 12.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = text.uppercase(),
            color = LcarsBlack,
            fontWeight = FontWeight.Bold,
            fontSize = 16.sp
        )
    }
}

@Composable
fun LcarsNavigationBar(
    items: List<String>,
    selectedItem: String,
    onItemSelected: (String) -> Unit,
    activeTabIds: Set<String> = emptySet(),
    hasAlert: Boolean = false
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .background(LcarsBlack)
            .padding(top = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // Decorative elbow piece
        Box(
            modifier = Modifier
                .width(56.dp)
                .fillMaxHeight()
                .clip(RoundedCornerShape(topEnd = 28.dp))
                .background(LcarsOrange)
        )
        
        Spacer(modifier = Modifier.width(8.dp))
        
        Row(
            modifier = Modifier
                .weight(1f)
                .horizontalScroll(rememberScrollState()),
            verticalAlignment = Alignment.CenterVertically
        ) {
            items.forEachIndexed { index, item ->
                val isSelected = item == selectedItem
                val isActive = item in activeTabIds
                val showAlert = item == "HOME" && hasAlert
                val color = when (item) {
                    "ENV" -> if (isSelected) LcarsOrange else LcarsTan
                    "GEO" -> if (isSelected) LcarsBlue else LcarsPurple
                    "EM" -> if (isSelected) LcarsPink else LcarsPurple
                    "HOME" -> if (isSelected) LcarsOrange else LcarsTan
                    "ACO" -> if (isSelected) LcarsRed else LcarsTan
                    "BIO" -> if (isSelected) LcarsBlue else LcarsTan
                    "RAD" -> if (isSelected) LcarsPink else LcarsTan
                    "MAP" -> if (isSelected) LcarsBlue else LcarsTan
                    "PIPE" -> if (isSelected) LcarsOrange else LcarsTan
                    else -> if (isSelected) LcarsOrange else LcarsTan
                }
                
                LcarsNavButton(
                    text = item,
                    onClick = { onItemSelected(item) },
                    color = color,
                    isSelected = isSelected,
                    isActive = isActive,
                    showAlert = showAlert
                )
                
                if (index < items.lastIndex) {
                    Spacer(modifier = Modifier.width(4.dp))
                }
            }
        } // end scrollable Row
        
        Spacer(modifier = Modifier.width(8.dp))
        
        // End decorative cap
        Box(
            modifier = Modifier
                .width(32.dp)
                .fillMaxHeight()
                .clip(RoundedCornerShape(topStart = 16.dp, bottomStart = 16.dp))
                .background(LcarsTan)
        )
    }
}

@Composable
private fun LcarsNavButton(
    text: String,
    onClick: () -> Unit,
    color: Color,
    isSelected: Boolean,
    isActive: Boolean = false,
    showAlert: Boolean = false
) {
    // Blinking animation for alert dot
    val infiniteTransition = rememberInfiniteTransition(label = "alertBlink")
    val alertAlpha by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = 0.2f,
        animationSpec = infiniteRepeatable(
            animation = tween(500, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "alertAlpha"
    )
    
    val icon = getTabIcon(text)
    
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(topStart = 12.dp, bottomStart = 12.dp))
            .background(color)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            // Icon/symbol row with optional alert dot
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center
            ) {
                Text(
                    text = icon,
                    color = LcarsBlack,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Normal
                )
                
                // Alert blinking dot (only on HOME when hasAlert is true)
                if (showAlert) {
                    Spacer(modifier = Modifier.width(2.dp))
                    Box(
                        modifier = Modifier
                            .size(4.dp)
                            .clip(CircleShape)
                            .background(LcarsRed.copy(alpha = alertAlpha))
                    )
                }
            }
            
            Spacer(modifier = Modifier.height(2.dp))
            
            // Status dot indicator
            Box(
                modifier = Modifier
                    .size(4.dp)
                    .clip(CircleShape)
                    .background(
                        if (isActive) LcarsOrange else Color.Gray.copy(alpha = 0.4f)
                    )
            )
            
            Spacer(modifier = Modifier.height(2.dp))
            
            // Label
            Text(
                text = text.uppercase(),
                color = LcarsBlack,
                fontWeight = if (isSelected) FontWeight.ExtraBold else FontWeight.Bold,
                fontSize = if (isSelected) 18.sp else 16.sp
            )
        }
    }
}
