package com.solomonprime.tricorder.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.solomonprime.tricorder.model.AlertThreshold
import com.solomonprime.tricorder.ui.theme.*

@Composable
fun AlertSettingsScreen(
    thresholds: List<AlertThreshold>,
    onToggle: (AlertThreshold) -> Unit,
    onClearAll: () -> Unit,
    modifier: Modifier = Modifier
) {
    LazyColumn(
        modifier = modifier
            .fillMaxSize()
            .background(LcarsBlack)
            .padding(horizontal = 12.dp),
        contentPadding = PaddingValues(vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        item {
            LcarsSectionHeader(title = "Alert Thresholds", color = LcarsRed)
            Spacer(modifier = Modifier.height(4.dp))
        }

        items(thresholds, key = { it.id }) { threshold ->
            AlertThresholdRow(
                threshold = threshold,
                onToggle = { onToggle(threshold) }
            )
        }

        item {
            Spacer(modifier = Modifier.height(16.dp))
            LcarsButton(
                text = "Clear All Alerts",
                onClick = onClearAll,
                color = LcarsRed,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

@Composable
private fun AlertThresholdRow(
    threshold: AlertThreshold,
    onToggle: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(4.dp))
            .background(LcarsBlack)
            .padding(horizontal = 8.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // Accent pip
        Box(
            modifier = Modifier
                .width(6.dp)
                .height(40.dp)
                .clip(RoundedCornerShape(3.dp))
                .background(if (threshold.enabled) LcarsOrange else LcarsTan.copy(alpha = 0.4f))
        )

        Spacer(modifier = Modifier.width(10.dp))

        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = threshold.label.uppercase(),
                color = if (threshold.enabled) LcarsOrange else LcarsTan.copy(alpha = 0.6f),
                fontSize = 14.sp,
                fontWeight = FontWeight.Bold
            )
            val rangeText = buildString {
                threshold.minValue?.let { append("Min: %.0f".format(it)) }
                if (threshold.minValue != null && threshold.maxValue != null) append("  ·  ")
                threshold.maxValue?.let { append("Max: %.0f".format(it)) }
            }
            if (rangeText.isNotEmpty()) {
                Text(
                    text = rangeText,
                    color = LcarsWhite.copy(alpha = 0.5f),
                    fontSize = 12.sp
                )
            }
        }

        Switch(
            checked = threshold.enabled,
            onCheckedChange = { onToggle() },
            colors = SwitchDefaults.colors(
                checkedThumbColor = LcarsOrange,
                checkedTrackColor = LcarsOrange.copy(alpha = 0.4f),
                uncheckedThumbColor = LcarsTan,
                uncheckedTrackColor = LcarsTan.copy(alpha = 0.2f)
            )
        )
    }
}
